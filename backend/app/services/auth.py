"""Regras de autenticação do UC01 (RF01)."""

import logging
import math
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_password_hash,
    gerar_token_opaco,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.convite import Convite
from app.models.empresa import Empresa
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.token_redefinicao_senha import TokenRedefinicaoSenha
from app.models.usuario import Usuario
from app.schemas.auth import UserRegister
from app.services import termos as termos_service

logger = logging.getLogger(__name__)

# UC01: 5 tentativas malsucedidas no mesmo e-mail em 10 min -> bloqueio de 15 min
MAX_TENTATIVAS = 5
JANELA_TENTATIVAS = timedelta(minutes=10)
DURACAO_BLOQUEIO = timedelta(minutes=15)
# Para o bloqueio bastariam JANELA + DURACAO (25 min); guardamos 24h para ainda enxergar
# o volume de um ataque recente contra um e-mail. Além disso a linha não serve para nada.
RETENCAO_TENTATIVAS = timedelta(hours=24)

PAPEL_PADRAO = "usuario_pme"
PAPEL_ADMIN = "admin"

PAPEL_DONO = "dono"
PAPEL_MEMBRO = "membro"

# Redefinição de senha: link de 30 min, uso único. No máximo 3 links por conta por
# hora — acima disso o pedido é aceito (202, igual) e simplesmente não gera e-mail.
VALIDADE_REDEFINICAO = timedelta(minutes=30)
MAX_REDEFINICOES_POR_HORA = 3

# UC01: a mesma mensagem para e-mail inexistente e para senha errada — a resposta
# não pode revelar se a conta existe.
CREDENCIAIS_INVALIDAS = "E-mail ou senha inválidos."
# A mesma mensagem para convite inexistente, adulterado, expirado, já usado ou de
# outro e-mail: a resposta não ajuda a adivinhar qual parte está errada.
CONVITE_INVALIDO = "Convite inválido ou expirado."
EMPRESA_LOTADA = "A empresa atingiu o limite de membros."
LINK_REDEFINICAO_INVALIDO = "Link de redefinição inválido ou expirado."
REFRESH_INVALIDO = "Refresh token inválido ou expirado."
BLOQUEADO = "Muitas tentativas malsucedidas. Tente novamente mais tarde."


def normalizar_email(email: str) -> str:
    """Sem isso, `A@x.com` e `a@x.com` teriam contadores de bloqueio separados."""
    return email.strip().lower()


def _as_utc(momento: datetime) -> datetime:
    """Alguns drivers devolvem datetime sem tzinfo; gravamos sempre em UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- cadastro


async def contar_membros(db: AsyncSession, id_empresa: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(Usuario).where(Usuario.id_empresa == id_empresa)
    )


async def consultar_convite(db: AsyncSession, token: str) -> tuple[Convite, Empresa]:
    """Convite pendente pelo token, para a tela de cadastro preencher e travar o e-mail.

    Só quem tem o token chega aqui, e ele já está no link que o convidado recebeu —
    devolver o e-mail e o nome da empresa não revela nada que ele não tenha.
    """
    convite = await db.scalar(select(Convite).where(Convite.token_hash == hash_token(token)))
    if (
        convite is None
        or convite.usado_em is not None
        or _as_utc(convite.expira_em) <= datetime.now(UTC)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CONVITE_INVALIDO)
    empresa = await db.get(Empresa, convite.id_empresa)
    return convite, empresa


async def _consumir_convite(db: AsyncSession, token: str, email: str) -> Convite:
    """Valida o convite e o CONSOME. Levanta 400 (inválido) ou 409 (empresa lotada)."""
    invalido = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CONVITE_INVALIDO)

    convite = await db.scalar(select(Convite).where(Convite.token_hash == hash_token(token)))
    if (
        convite is None
        or convite.usado_em is not None
        or _as_utc(convite.expira_em) <= datetime.now(UTC)
        or convite.email != email
    ):
        raise invalido

    # Trava a linha da empresa: dois cadastros simultâneos por convites diferentes
    # não podem, cada um, contar 9 membros e entrar os dois. No SQLite dos testes o
    # FOR UPDATE é ignorado; a regra continua valendo em série.
    await db.execute(
        select(Empresa.id_empresa).where(Empresa.id_empresa == convite.id_empresa).with_for_update()
    )
    if await contar_membros(db, convite.id_empresa) >= settings.empresa_max_membros:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EMPRESA_LOTADA)
    # Teto de donos (ADR-013): a emissão já conta os convites de dono pendentes; aqui
    # é a segunda linha, para uma promoção feita depois do convite.
    if convite.papel_empresa == PAPEL_DONO:
        donos = await db.scalar(
            select(func.count())
            .select_from(Usuario)
            .where(Usuario.id_empresa == convite.id_empresa, Usuario.papel_empresa == PAPEL_DONO)
        )
        if donos >= settings.empresa_max_donos:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A empresa já tem o máximo de {settings.empresa_max_donos} donos.",
            )

    # Uso único garantido pelo banco: só um UPDATE encontra `usado_em` nulo.
    consumido = await db.execute(
        update(Convite)
        .execution_options(synchronize_session="fetch")
        .where(Convite.id_convite == convite.id_convite, Convite.usado_em.is_(None))
        .values(usado_em=datetime.now(UTC))
    )
    if consumido.rowcount != 1:
        raise invalido
    return convite


async def register_user(db: AsyncSession, dados: UserRegister) -> Usuario:
    """Cria a conta: dona de uma empresa nova, ou membro da empresa do convite."""
    email = normalizar_email(dados.email)

    existente = await db.scalar(select(Usuario).where(Usuario.email == email))
    if existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma conta com este e-mail.",
        )

    if dados.token_convite is not None:
        convite = await _consumir_convite(db, dados.token_convite, email)
        id_empresa, papel_empresa = convite.id_empresa, convite.papel_empresa
    else:
        empresa = Empresa(nome=dados.nome_empresa)
        db.add(empresa)
        # flush para o banco atribuir o id que o usuário referencia; a empresa e o
        # dono nascem na mesma transação.
        await db.flush()
        id_empresa, papel_empresa = empresa.id_empresa, PAPEL_DONO

    usuario = Usuario(
        nome=dados.nome.strip(),
        email=email,
        senha_hash=hash_password(dados.senha.get_secret_value()),
        # Nunca vem do cliente: aceitar `papel` na requisição permitiria criar admin.
        papel=PAPEL_PADRAO,
        id_empresa=id_empresa,
        papel_empresa=papel_empresa,
    )
    db.add(usuario)
    try:
        # flush para ter o id que o aceite referencia; conta e aceite saem no MESMO
        # commit (ADR-012). O UNIQUE do e-mail pode estourar já aqui.
        await db.flush()
        termos_service.registrar_aceite(db, usuario.id_usuario)
        await db.commit()
    except IntegrityError:
        # Corrida com outro cadastro do mesmo e-mail: o UNIQUE do banco decide.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma conta com este e-mail.",
        ) from None
    await db.refresh(usuario, ["empresa"])

    logger.info(
        "usuario registrado id_usuario=%s id_empresa=%s papel_empresa=%s via_convite=%s",
        usuario.id_usuario,
        usuario.id_empresa,
        usuario.papel_empresa,
        dados.token_convite is not None,
    )
    return usuario


# --------------------------------------------------------------------------- login


async def _bloqueado_ate(db: AsyncSession, email_hash: str) -> datetime | None:
    """Instante em que o bloqueio termina, ou None se o e-mail não está bloqueado."""
    tentativas = list(
        await db.scalars(
            select(TentativaLogin.tentado_em)
            .where(TentativaLogin.email_hash == email_hash)
            .order_by(TentativaLogin.tentado_em.desc())
            .limit(MAX_TENTATIVAS)
        )
    )
    if len(tentativas) < MAX_TENTATIVAS:
        return None

    mais_recente = _as_utc(tentativas[0])
    mais_antiga = _as_utc(tentativas[-1])
    if mais_recente - mais_antiga > JANELA_TENTATIVAS:
        # As 5 falhas existem, mas espalhadas por mais de 10 min: não dispara bloqueio.
        return None

    fim_do_bloqueio = mais_recente + DURACAO_BLOQUEIO
    return fim_do_bloqueio if fim_do_bloqueio > datetime.now(UTC) else None


def _erro_bloqueio(bloqueado_ate: datetime) -> HTTPException:
    segundos = max(1, math.ceil((bloqueado_ate - datetime.now(UTC)).total_seconds()))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=BLOQUEADO,
        headers={"Retry-After": str(segundos)},
    )


async def _registrar_falha(db: AsyncSession, email_hash: str) -> None:
    agora = datetime.now(UTC)
    db.add(TentativaLogin(email_hash=email_hash, tentado_em=agora))
    # Poda aproveitando a escrita que já está acontecendo — evita job agendado.
    await db.execute(
        delete(TentativaLogin).where(
            TentativaLogin.email_hash == email_hash,
            TentativaLogin.tentado_em < agora - RETENCAO_TENTATIVAS,
        )
    )
    await db.commit()


async def authenticate(db: AsyncSession, email: str, senha: str) -> Usuario:
    email = normalizar_email(email)
    # Normaliza antes de hashear: senão `A@x.com` e `a@x.com` teriam hashes
    # diferentes e cada variação ganharia seu próprio contador de bloqueio.
    email_hash = hash_token(email)

    # O bloqueio é verificado ANTES de conferir a senha: senha correta não fura bloqueio.
    bloqueado_ate = await _bloqueado_ate(db, email_hash)
    if bloqueado_ate is not None:
        logger.warning("login bloqueado por excesso de tentativas email_hash=%s", email_hash)
        raise _erro_bloqueio(bloqueado_ate)

    usuario = await db.scalar(select(Usuario).where(Usuario.email == email))

    if usuario is None:
        # Compara contra um hash descartável só para gastar o mesmo tempo do caminho
        # normal — senão o tempo de resposta revelaria que o e-mail não existe.
        verify_password(senha, dummy_password_hash())
        await _registrar_falha(db, email_hash)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENCIAIS_INVALIDAS)

    if not verify_password(senha, usuario.senha_hash):
        await _registrar_falha(db, email_hash)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENCIAIS_INVALIDAS)

    await db.execute(delete(TentativaLogin).where(TentativaLogin.email_hash == email_hash))
    await db.commit()

    logger.info("login bem-sucedido id_usuario=%s", usuario.id_usuario)
    return usuario


# --------------------------------------------------------------------------- refresh


async def issue_token_pair(db: AsyncSession, usuario: Usuario) -> tuple[str, str]:
    access_token = create_access_token(usuario.id_usuario, usuario.papel)
    refresh_token, expira_em = create_refresh_token(usuario.id_usuario)

    db.add(
        TokenAtualizacao(
            id_usuario=usuario.id_usuario,
            token_hash=hash_token(refresh_token),
            expira_em=expira_em,
        )
    )
    # Regra 7 do CLAUDE.md: com rotação, cada refresh deixa uma linha. As vencidas
    # não servem nem para detectar reuso (o JWT expirado já é recusado antes), então
    # saem aqui, na escrita que já está acontecendo. As substituídas e ainda dentro
    # do prazo FICAM: são elas que denunciam o reuso.
    await db.execute(
        delete(TokenAtualizacao)
        .execution_options(synchronize_session="fetch")
        .where(
            TokenAtualizacao.id_usuario == usuario.id_usuario,
            TokenAtualizacao.expira_em < datetime.now(UTC),
        )
    )
    await db.commit()
    return access_token, refresh_token


async def revogar_todos_os_refresh(db: AsyncSession, id_usuario: int) -> int:
    """Revoga todos os refresh tokens ativos do usuário. NÃO faz commit."""
    resultado = await db.execute(
        update(TokenAtualizacao)
        .execution_options(synchronize_session="fetch")
        .where(TokenAtualizacao.id_usuario == id_usuario, TokenAtualizacao.revogado.is_(False))
        .values(revogado=True)
    )
    return resultado.rowcount


async def _reuso_detectado(db: AsyncSession, registro: TokenAtualizacao) -> HTTPException:
    """Um token já trocado reapareceu: alguém tem uma cópia. Derruba a família inteira.

    A família é o conjunto de refresh tokens do usuário. Não dá para saber qual dos
    dois é o legítimo — o dono, que já recebeu o sucessor, ou quem copiou o antigo —,
    então os dois perdem a sessão e o dono entra de novo com a senha.
    """
    id_usuario, id_token = registro.id_usuario, registro.id_token
    revogados = await revogar_todos_os_refresh(db, id_usuario)
    await db.commit()
    logger.warning(
        "evento=refresh_token_reuso id_usuario=%s id_token=%s tokens_revogados=%s",
        id_usuario,
        id_token,
        revogados,
    )
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=REFRESH_INVALIDO)


async def _carregar_refresh_valido(db: AsyncSession, refresh_token: str) -> TokenAtualizacao:
    erro = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=REFRESH_INVALIDO)

    payload = decode_token(refresh_token, TOKEN_TYPE_REFRESH)
    if payload is None:
        raise erro

    registro = await db.scalar(
        select(TokenAtualizacao).where(TokenAtualizacao.token_hash == hash_token(refresh_token))
    )
    if registro is None:
        raise erro
    # Reuso antes de "revogado": um token substituído que reaparece é sinal de cópia
    # mesmo que a família já tenha sido revogada depois.
    if registro.substituido_em is not None:
        raise await _reuso_detectado(db, registro)
    if registro.revogado:
        raise erro
    if _as_utc(registro.expira_em) <= datetime.now(UTC):
        raise erro
    return registro


async def rotate_refresh_token(db: AsyncSession, refresh_token: str) -> tuple[str, str]:
    """Troca o refresh por um par novo e invalida o antigo (rotação)."""
    registro = await _carregar_refresh_valido(db, refresh_token)

    usuario = await db.get(Usuario, registro.id_usuario)
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=REFRESH_INVALIDO)

    # Marca como substituído só se ninguém marcou antes: duas chamadas simultâneas
    # com o mesmo token não podem ambas ganhar um sucessor. A que perde é reuso.
    marcado = await db.execute(
        update(TokenAtualizacao)
        .execution_options(synchronize_session="fetch")
        .where(
            TokenAtualizacao.id_token == registro.id_token,
            TokenAtualizacao.substituido_em.is_(None),
            TokenAtualizacao.revogado.is_(False),
        )
        .values(substituido_em=datetime.now(UTC))
    )
    if marcado.rowcount != 1:
        raise await _reuso_detectado(db, registro)

    return await issue_token_pair(db, usuario)


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    registro = await _carregar_refresh_valido(db, refresh_token)
    registro.revogado = True
    await db.commit()
    logger.info("refresh token revogado id_usuario=%s", registro.id_usuario)


# --------------------------------------------------------------------------- senha


async def conferir_senha_atual(db: AsyncSession, usuario: Usuario, senha: str) -> bool:
    """Confere a senha de quem JÁ está logado, sob o mesmo bloqueio do login.

    Levanta 429 se o e-mail está bloqueado. A senha errada conta como tentativa de
    login malsucedida, no mesmo contador (e faz commit dela): sem isso, um access
    token roubado viraria um jeito de testar senhas sem bloqueio. Devolve se conferiu;
    a resposta de erro fica com quem chama.
    """
    email_hash = hash_token(usuario.email)
    bloqueado_ate = await _bloqueado_ate(db, email_hash)
    if bloqueado_ate is not None:
        raise _erro_bloqueio(bloqueado_ate)

    if not verify_password(senha, usuario.senha_hash):
        await _registrar_falha(db, email_hash)
        return False
    return True


async def trocar_senha(
    db: AsyncSession, usuario: Usuario, senha_atual: str, nova_senha: str
) -> tuple[str, str]:
    """Troca a senha de quem está logado e devolve um par novo para esta sessão."""
    if not await conferir_senha_atual(db, usuario, senha_atual):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Senha atual incorreta."
        )
    if senha_atual == nova_senha:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A nova senha deve ser diferente da atual.",
        )

    usuario.senha_hash = hash_password(nova_senha)
    # Toda sessão aberta com a senha antiga cai: se a troca foi por suspeita de
    # vazamento, um refresh token já copiado não pode continuar valendo.
    revogados = await revogar_todos_os_refresh(db, usuario.id_usuario)
    await db.commit()
    logger.info("senha trocada id_usuario=%s refresh_revogados=%s", usuario.id_usuario, revogados)
    return await issue_token_pair(db, usuario)


async def solicitar_redefinicao(db: AsyncSession, email: str) -> tuple[str, str] | None:
    """Gera o link de redefinição, se houver conta. Devolve (destinatário, token) ou None.

    Quem chama responde 202 IGUAL nos dois casos e manda o e-mail em segundo plano:
    nem o corpo nem o tempo de resposta podem dizer se o e-mail tem conta.
    """
    email = normalizar_email(email)
    usuario = await db.scalar(select(Usuario).where(Usuario.email == email))
    if usuario is None:
        logger.info("redefinicao pedida para e-mail sem conta")
        return None

    agora = datetime.now(UTC)
    uma_hora_atras = agora - timedelta(hours=1)
    recentes = await db.scalar(
        select(func.count())
        .select_from(TokenRedefinicaoSenha)
        .where(
            TokenRedefinicaoSenha.id_usuario == usuario.id_usuario,
            TokenRedefinicaoSenha.criado_em > uma_hora_atras,
        )
    )
    if recentes >= MAX_REDEFINICOES_POR_HORA:
        logger.warning("redefinicao limitada por conta id_usuario=%s", usuario.id_usuario)
        return None

    # Regra 7: os da última hora ficam, porque são o contador do limite acima; os
    # mais velhos já venceram (30 min) e saem. Só o link mais recente vale: os
    # anteriores ainda abertos são encerrados.
    await db.execute(
        delete(TokenRedefinicaoSenha)
        .execution_options(synchronize_session="fetch")
        .where(
            TokenRedefinicaoSenha.id_usuario == usuario.id_usuario,
            TokenRedefinicaoSenha.criado_em <= uma_hora_atras,
        )
    )
    await db.execute(
        update(TokenRedefinicaoSenha)
        .execution_options(synchronize_session="fetch")
        .where(
            TokenRedefinicaoSenha.id_usuario == usuario.id_usuario,
            TokenRedefinicaoSenha.usado_em.is_(None),
        )
        .values(usado_em=agora)
    )

    token = gerar_token_opaco()
    db.add(
        TokenRedefinicaoSenha(
            id_usuario=usuario.id_usuario,
            token_hash=hash_token(token),
            expira_em=agora + VALIDADE_REDEFINICAO,
            criado_em=agora,
        )
    )
    await db.commit()
    logger.info("link de redefinicao gerado id_usuario=%s", usuario.id_usuario)
    return usuario.email, token


async def redefinir_senha(db: AsyncSession, token: str, nova_senha: str) -> None:
    invalido = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail=LINK_REDEFINICAO_INVALIDO
    )
    registro = await db.scalar(
        select(TokenRedefinicaoSenha).where(TokenRedefinicaoSenha.token_hash == hash_token(token))
    )
    if (
        registro is None
        or registro.usado_em is not None
        or _as_utc(registro.expira_em) <= datetime.now(UTC)
    ):
        raise invalido

    consumido = await db.execute(
        update(TokenRedefinicaoSenha)
        .execution_options(synchronize_session="fetch")
        .where(
            TokenRedefinicaoSenha.id_token == registro.id_token,
            TokenRedefinicaoSenha.usado_em.is_(None),
        )
        .values(usado_em=datetime.now(UTC))
    )
    if consumido.rowcount != 1:
        raise invalido

    usuario = await db.get(Usuario, registro.id_usuario)
    if usuario is None:
        raise invalido

    usuario.senha_hash = hash_password(nova_senha)
    revogados = await revogar_todos_os_refresh(db, usuario.id_usuario)
    # Quem provou a posse do e-mail sai do bloqueio por tentativas.
    await db.execute(
        delete(TentativaLogin).where(TentativaLogin.email_hash == hash_token(usuario.email))
    )
    await db.commit()
    logger.info(
        "senha redefinida id_usuario=%s refresh_revogados=%s", usuario.id_usuario, revogados
    )


def link_do_frontend(caminho: str, token: str) -> str:
    """Link absoluto para uma tela do frontend com o token na query string."""
    return f"{settings.frontend_url.rstrip('/')}{caminho}?{token}"


def email_redefinicao(token: str) -> tuple[str, str]:
    """(assunto, texto) do e-mail de redefinição."""
    minutos = int(VALIDADE_REDEFINICAO.total_seconds() // 60)
    return (
        "Redefinição de senha — Emi Analytics",
        "Recebemos um pedido para redefinir a sua senha.\n\n"
        f"Abra o link abaixo em até {minutos} minutos:\n"
        f"{link_do_frontend('/redefinir-senha', f'token={token}')}\n\n"
        "Se não foi você, ignore este e-mail: a sua senha continua a mesma.",
    )
