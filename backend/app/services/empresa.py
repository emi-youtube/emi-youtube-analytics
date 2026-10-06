"""Gestão da empresa: membros e convites (ADR-011).

Só o DONO gerencia — a checagem é a dependency `requer_dono` no router. Todo
recurso é procurado DENTRO da empresa de quem chama: membro ou convite de outra
empresa responde 404, igual a um id que não existe.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import gerar_token_opaco, hash_token
from app.models.convite import Convite
from app.models.empresa import Empresa
from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario
from app.schemas.empresa import ConviteCreate
from app.services.auth import (
    EMPRESA_LOTADA,
    PAPEL_DONO,
    PAPEL_MEMBRO,
    contar_membros,
    link_do_frontend,
    normalizar_email,
)

logger = logging.getLogger(__name__)

VALIDADE_CONVITE = timedelta(days=7)

ULTIMO_DONO = "A empresa precisa de ao menos um dono."


def limite_de_donos() -> str:
    return f"A empresa já tem o máximo de {settings.empresa_max_donos} donos."


async def contar_donos(db: AsyncSession, id_empresa: int) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(Usuario)
        .where(Usuario.id_empresa == id_empresa, Usuario.papel_empresa == PAPEL_DONO)
    )


async def _donos_reservados(db: AsyncSession, id_empresa: int, agora: datetime) -> int:
    """Donos atuais + convites de dono pendentes: o teto conta as vagas reservadas,
    como o de membros, senão três convites de dono furariam o limite."""
    pendentes = await db.scalar(
        select(func.count())
        .select_from(Convite)
        .where(*_pendentes(id_empresa, agora), Convite.papel_empresa == PAPEL_DONO)
    )
    return await contar_donos(db, id_empresa) + pendentes


def _pendentes(id_empresa: int, agora: datetime):
    return (
        Convite.id_empresa == id_empresa,
        Convite.usado_em.is_(None),
        Convite.expira_em > agora,
    )


async def listar_membros(db: AsyncSession, usuario: Usuario) -> Sequence[Usuario]:
    resultado = await db.scalars(
        select(Usuario)
        .where(Usuario.id_empresa == usuario.id_empresa)
        .order_by(Usuario.criado_em, Usuario.id_usuario)
    )
    return resultado.all()


async def listar_convites(db: AsyncSession, usuario: Usuario) -> Sequence[Convite]:
    """Só os pendentes: usado ou vencido não é mais ação para o dono."""
    resultado = await db.scalars(
        select(Convite)
        .where(*_pendentes(usuario.id_empresa, datetime.now(UTC)))
        .order_by(Convite.criado_em.desc(), Convite.id_convite.desc())
    )
    return resultado.all()


async def criar_convite(
    db: AsyncSession, dono: Usuario, dados: ConviteCreate
) -> tuple[Convite, str]:
    """Cria o convite e devolve (convite, token). O token sai daqui e nunca mais.

    A resposta é a mesma exista ou não uma conta com aquele e-mail, em qualquer
    empresa: o convite não pode virar consulta de "este e-mail usa o sistema?". Se o
    e-mail já tiver conta, o cadastro pelo convite é que vai recusar.
    """
    email = normalizar_email(dados.email)
    agora = datetime.now(UTC)

    # Trava a empresa: dois convites simultâneos não podem, cada um, ver uma vaga.
    await db.execute(
        select(Empresa.id_empresa).where(Empresa.id_empresa == dono.id_empresa).with_for_update()
    )

    # Regra 7: convite vencido não volta a valer; sai na escrita, como as tentativas
    # de login. Os USADOS também saem quando vencem — o registro de quem entrou é a
    # própria linha em USUARIOS.
    await db.execute(
        delete(Convite)
        .execution_options(synchronize_session="fetch")
        .where(Convite.id_empresa == dono.id_empresa, Convite.expira_em <= agora)
    )
    # Um convite pendente por e-mail: gerar de novo substitui o anterior.
    await db.execute(
        delete(Convite)
        .execution_options(synchronize_session="fetch")
        .where(
            *_pendentes(dono.id_empresa, agora),
            Convite.email == email,
        )
    )

    pendentes = await db.scalar(
        select(func.count()).select_from(Convite).where(*_pendentes(dono.id_empresa, agora))
    )
    # Convites pendentes contam como vagas reservadas: sem isso o dono emitiria 50
    # convites numa empresa de 10.
    if await contar_membros(db, dono.id_empresa) + pendentes >= settings.empresa_max_membros:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EMPRESA_LOTADA)
    if (
        dados.papel_empresa == PAPEL_DONO
        and await _donos_reservados(db, dono.id_empresa, agora) >= settings.empresa_max_donos
    ):
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=limite_de_donos())

    token = gerar_token_opaco()
    convite = Convite(
        id_empresa=dono.id_empresa,
        email=email,
        token_hash=hash_token(token),
        papel_empresa=dados.papel_empresa,
        criado_por=dono.id_usuario,
        expira_em=agora + VALIDADE_CONVITE,
        criado_em=agora,
    )
    db.add(convite)
    await db.commit()
    await db.refresh(convite)

    logger.info(
        "convite criado id_convite=%s id_empresa=%s papel_empresa=%s criado_por=%s",
        convite.id_convite,
        convite.id_empresa,
        convite.papel_empresa,
        dono.id_usuario,
    )
    return convite, token


def link_convite(token: str) -> str:
    return link_do_frontend("/entrar", f"convite={token}")


def email_convite(nome_empresa: str, token: str) -> tuple[str, str]:
    """(assunto, texto) do e-mail de convite."""
    dias = VALIDADE_CONVITE.days
    return (
        f"Convite para {nome_empresa} — Emi Analytics",
        f"Você foi convidado para a empresa {nome_empresa} no Emi Analytics.\n\n"
        f"Crie a sua conta pelo link abaixo (vale por {dias} dias e uma única vez):\n"
        f"{link_convite(token)}\n\n"
        "Se não esperava este convite, ignore este e-mail.",
    )


async def revogar_convite(db: AsyncSession, dono: Usuario, id_convite: int) -> None:
    removido = await db.execute(
        delete(Convite)
        .execution_options(synchronize_session="fetch")
        .where(
            Convite.id_convite == id_convite,
            *_pendentes(dono.id_empresa, datetime.now(UTC)),
        )
    )
    if removido.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Convite não encontrado.")
    await db.commit()
    logger.info(
        "convite revogado id_convite=%s id_empresa=%s por=%s",
        id_convite,
        dono.id_empresa,
        dono.id_usuario,
    )


async def remover_membro(db: AsyncSession, dono: Usuario, id_usuario: int) -> None:
    """Remove a pessoa da empresa, o que aqui é apagar a conta dela.

    Não existe usuário sem empresa (`id_empresa` NOT NULL): sair da empresa é sair do
    sistema. Os dados são da EMPRESA e ficam: a autoria dos modelos que a pessoa
    criou passa para o dono que a removeu, porque `modelos_analise.id_usuario` é
    obrigatório e o modelo continua precisando de alguém que responda por ele. Os
    refresh tokens, convites e links de redefinição dela saem em cascata; o access
    token em mãos deixa de valer na hora, porque `get_usuario_atual` relê o usuário.
    """
    if id_usuario == dono.id_usuario:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Você não pode remover a si mesmo da empresa.",
        )

    alvo = await db.scalar(
        select(Usuario).where(
            Usuario.id_usuario == id_usuario, Usuario.id_empresa == dono.id_empresa
        )
    )
    if alvo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro não encontrado.")

    if alvo.papel_empresa == PAPEL_DONO and await contar_donos(db, dono.id_empresa) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ULTIMO_DONO)

    modelos_transferidos = await db.execute(
        update(ModeloAnalise)
        .where(ModeloAnalise.id_usuario == alvo.id_usuario)
        .values(id_usuario=dono.id_usuario)
    )
    await db.delete(alvo)
    await db.commit()

    logger.info(
        "membro removido id_usuario=%s id_empresa=%s por=%s modelos_transferidos=%s",
        id_usuario,
        dono.id_empresa,
        dono.id_usuario,
        modelos_transferidos.rowcount,
    )


async def alterar_papel(
    db: AsyncSession, dono: Usuario, id_usuario: int, papel_empresa: str
) -> Usuario:
    """Promove a dono ou rebaixa a membro (ADR-013). Só o dono chama (`requer_dono`).

    Alvo de outra empresa: 404, igual a um id que não existe. Rebaixar exige que
    sobre outro dono — vale também para rebaixar a si mesmo. Promover respeita o teto
    de donos. Não há sessão a revogar: `get_usuario_atual` relê o usuário a cada
    requisição, então o rebaixado perde as rotas de dono já na próxima chamada, com
    o mesmo token.
    """
    # Trava a empresa: dois donos rebaixando um ao outro ao mesmo tempo não podem,
    # cada um, ver "sobra outro dono" e deixar a empresa sem nenhum.
    await db.execute(
        select(Empresa.id_empresa).where(Empresa.id_empresa == dono.id_empresa).with_for_update()
    )
    alvo = await db.scalar(
        select(Usuario).where(
            Usuario.id_usuario == id_usuario, Usuario.id_empresa == dono.id_empresa
        )
    )
    if alvo is None:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro não encontrado.")

    anterior = alvo.papel_empresa
    if anterior == papel_empresa:
        await db.rollback()
        return alvo

    if papel_empresa == PAPEL_MEMBRO and await contar_donos(db, dono.id_empresa) <= 1:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ULTIMO_DONO)
    if (
        papel_empresa == PAPEL_DONO
        and await _donos_reservados(db, dono.id_empresa, datetime.now(UTC))
        >= settings.empresa_max_donos
    ):
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=limite_de_donos())

    alvo.papel_empresa = papel_empresa
    await db.commit()
    await db.refresh(alvo)

    logger.info(
        "evento=papel_alterado id_empresa=%s alvo=%s de=%s para=%s por=%s",
        dono.id_empresa,
        alvo.id_usuario,
        anterior,
        papel_empresa,
        dono.id_usuario,
    )
    return alvo
