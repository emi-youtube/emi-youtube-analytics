"""Direitos do titular sobre a própria conta (LGPD, ADR-012): acesso e eliminação.

Acesso: `meus_dados` devolve o que o sistema guarda SOBRE A PESSOA — não o que ela
produziu para a empresa, nem dados de colegas.

Eliminação: `excluir_conta`. O que some depende do papel, porque os dados de
análise são da EMPRESA (ADR-011), não de quem os criou:

- membro: sai a conta; os modelos que criou passam a um dono, como em
  `empresa.remover_membro`, e as análises ficam com a empresa;
- dono único: sai a empresa inteira, porque não sobra ninguém a quem ela pertença;
- dono com outros membros: recusado (409). Transferir a posse não existe ainda.
"""

import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.models.aceite_termos import AceiteTermos
from app.models.convite import Convite
from app.models.empresa import Empresa
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.token_redefinicao_senha import TokenRedefinicaoSenha
from app.models.usuario import Usuario
from app.models.video import Video
from app.services.auth import PAPEL_DONO, conferir_senha_atual

logger = logging.getLogger(__name__)

SENHA_INCORRETA = "Senha incorreta."
DONO_COM_MEMBROS = (
    "Você é dono de uma empresa com outros membros. Remova os membros antes de excluir a sua conta."
)
EXECUCAO_EM_ANDAMENTO = (
    "Há uma análise em andamento na empresa. Aguarde terminar antes de excluir a conta."
)


@dataclass(frozen=True)
class MeusDados:
    usuario: Usuario
    aceites: list[AceiteTermos]
    modelos: list[ModeloAnalise]


async def meus_dados(db: AsyncSession, usuario: Usuario) -> MeusDados:
    """Os dados da pessoa: cadastro, aceites e a autoria dos modelos.

    Os modelos entram só com nome e data — são da empresa; o que é da pessoa é
    tê-los criado. Nada aqui consulta outro usuário.
    """
    aceites = await db.scalars(
        select(AceiteTermos)
        .where(AceiteTermos.id_usuario == usuario.id_usuario)
        .order_by(AceiteTermos.aceito_em, AceiteTermos.id_aceite)
    )
    modelos = await db.scalars(
        select(ModeloAnalise)
        .where(ModeloAnalise.id_usuario == usuario.id_usuario)
        .order_by(ModeloAnalise.criado_em, ModeloAnalise.id_modelo)
    )
    return MeusDados(usuario=usuario, aceites=list(aceites), modelos=list(modelos))


async def _apagar_empresa(db: AsyncSession, id_empresa: int) -> dict[str, int]:
    """Apaga a empresa e tudo o que pende dela. NÃO faz commit.

    A ordem é imposta pelo schema: `execucoes`, `jobs`, `jobs_dlq` e `temas` NÃO
    têm ON DELETE CASCADE (apagar um modelo executado é barrado de propósito, ver
    `modelo_analise.delete`), então saem explicitamente, de baixo para cima.
    `videos` leva `comentarios`, que leva `analises_sentimento` e `comentario_tema`,
    por cascata do banco. `exemplos_treinamento` só perde a referência (SET NULL): o
    corpus de treino é do projeto, não da empresa (ADR-012).
    """
    modelos = select(ModeloAnalise.id_modelo).where(ModeloAnalise.id_empresa == id_empresa)
    execucoes = select(Execucao.id_execucao).where(Execucao.id_modelo.in_(modelos))

    contagens: dict[str, int] = {}
    for nome, tabela, coluna in (
        ("jobs_dlq", JobDlq, JobDlq.id_execucao),
        ("jobs", Job, Job.id_execucao),
        ("temas", Tema, Tema.id_execucao),
        ("videos", Video, Video.id_execucao),
    ):
        resultado = await db.execute(
            delete(tabela).execution_options(synchronize_session=False).where(coluna.in_(execucoes))
        )
        contagens[nome] = resultado.rowcount

    for nome, comando in (
        ("execucoes", delete(Execucao).where(Execucao.id_modelo.in_(modelos))),
        ("modelos", delete(ModeloAnalise).where(ModeloAnalise.id_empresa == id_empresa)),
        ("convites", delete(Convite).where(Convite.id_empresa == id_empresa)),
    ):
        resultado = await db.execute(comando.execution_options(synchronize_session=False))
        contagens[nome] = resultado.rowcount
    return contagens


async def excluir_conta(db: AsyncSession, usuario: Usuario, senha: str) -> None:
    """Exclui a conta de quem está logado. Tudo numa transação: falhou, nada sai.

    A senha é conferida sob o bloqueio do login (`conferir_senha_atual`): senha
    errada conta tentativa, e o 401 daqui não vira oráculo de senha sem limite.
    """
    if not await conferir_senha_atual(db, usuario, senha):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SENHA_INCORRETA)

    id_usuario, id_empresa = usuario.id_usuario, usuario.id_empresa

    # Trava a empresa: um convite aceito entre a contagem e o DELETE poria um membro
    # novo numa empresa que está sendo apagada. O cadastro por convite trava a mesma
    # linha (`auth._consumir_convite`). No SQLite dos testes o FOR UPDATE é ignorado.
    await db.execute(
        select(Empresa.id_empresa).where(Empresa.id_empresa == id_empresa).with_for_update()
    )
    outros_membros = await db.scalar(
        select(func.count())
        .select_from(Usuario)
        .where(Usuario.id_empresa == id_empresa, Usuario.id_usuario != id_usuario)
    )

    apagar_empresa = usuario.papel_empresa == PAPEL_DONO
    if apagar_empresa and outros_membros:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DONO_COM_MEMBROS)

    contagens: dict[str, int] = {}
    if apagar_empresa:
        # Um worker no meio de uma execução gravaria comentários de um vídeo que
        # acabou de sair, e a etapa terminaria em erro de chave estrangeira.
        em_andamento = await db.scalar(
            select(Execucao.id_execucao)
            .join(ModeloAnalise, ModeloAnalise.id_modelo == Execucao.id_modelo)
            .where(
                ModeloAnalise.id_empresa == id_empresa,
                Execucao.status.in_(("pendente", "processando")),
            )
            .limit(1)
        )
        if em_andamento is not None:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EXECUCAO_EM_ANDAMENTO)
        contagens = await _apagar_empresa(db, id_empresa)
    else:
        # Mesma regra de `empresa.remover_membro`: o modelo continua precisando de
        # alguém que responda por ele, e as execuções dele seguem com a empresa.
        dono = await db.scalar(
            select(Usuario.id_usuario)
            .where(Usuario.id_empresa == id_empresa, Usuario.papel_empresa == PAPEL_DONO)
            .order_by(Usuario.id_usuario)
            .limit(1)
        )
        transferidos = await db.execute(
            update(ModeloAnalise)
            .execution_options(synchronize_session=False)
            .where(ModeloAnalise.id_usuario == id_usuario)
            .values(id_usuario=dono)
        )
        contagens["modelos_transferidos"] = transferidos.rowcount

    # Sessões e links: o banco já os apagaria em cascata com o usuário; explícito
    # para não depender de o ORM emitir o DELETE antes de tudo o resto.
    for tabela, coluna in (
        (TokenAtualizacao, TokenAtualizacao.id_usuario),
        (TokenRedefinicaoSenha, TokenRedefinicaoSenha.id_usuario),
        (AceiteTermos, AceiteTermos.id_usuario),
    ):
        await db.execute(
            delete(tabela).execution_options(synchronize_session=False).where(coluna == id_usuario)
        )
    # Sem FK: as tentativas são por hash do e-mail, que deixa de ser de alguém.
    await db.execute(
        delete(TentativaLogin).where(TentativaLogin.email_hash == hash_token(usuario.email))
    )
    await db.execute(delete(Usuario).where(Usuario.id_usuario == id_usuario))
    if apagar_empresa:
        await db.execute(delete(Empresa).where(Empresa.id_empresa == id_empresa))

    await db.commit()
    db.expunge_all()

    logger.info(
        "evento=conta_excluida id_usuario=%s id_empresa=%s apagou_empresa=%s %s",
        id_usuario,
        id_empresa,
        str(apagar_empresa).lower(),
        " ".join(f"{nome}={total}" for nome, total in contagens.items()),
    )
