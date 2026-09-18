"""Regras de autenticação do UC01 (RF01)."""

import logging
import math
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_password_hash,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.usuario import Usuario
from app.schemas.auth import UserRegister

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

# UC01: a mesma mensagem para e-mail inexistente e para senha errada — a resposta
# não pode revelar se a conta existe.
CREDENCIAIS_INVALIDAS = "E-mail ou senha inválidos."


def normalizar_email(email: str) -> str:
    """Sem isso, `A@x.com` e `a@x.com` teriam contadores de bloqueio separados."""
    return email.strip().lower()


def _as_utc(momento: datetime) -> datetime:
    """Alguns drivers devolvem datetime sem tzinfo; gravamos sempre em UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


async def register_user(db: AsyncSession, dados: UserRegister) -> Usuario:
    email = normalizar_email(dados.email)

    existente = await db.scalar(select(Usuario).where(Usuario.email == email))
    if existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma conta com este e-mail.",
        )

    usuario = Usuario(
        nome=dados.nome.strip(),
        email=email,
        senha_hash=hash_password(dados.senha.get_secret_value()),
        # Nunca vem do cliente: aceitar `papel` na requisição permitiria criar admin.
        papel=PAPEL_PADRAO,
    )
    db.add(usuario)
    await db.commit()
    await db.refresh(usuario)

    logger.info("usuario registrado id_usuario=%s", usuario.id_usuario)
    return usuario


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
        segundos = max(1, math.ceil((bloqueado_ate - datetime.now(UTC)).total_seconds()))
        logger.warning("login bloqueado por excesso de tentativas email_hash=%s", email_hash)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas malsucedidas. Tente novamente mais tarde.",
            headers={"Retry-After": str(segundos)},
        )

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
    await db.commit()
    return access_token, refresh_token


async def _carregar_refresh_valido(db: AsyncSession, refresh_token: str) -> TokenAtualizacao:
    erro = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token inválido ou expirado.",
    )

    payload = decode_token(refresh_token, TOKEN_TYPE_REFRESH)
    if payload is None:
        raise erro

    registro = await db.scalar(
        select(TokenAtualizacao).where(TokenAtualizacao.token_hash == hash_token(refresh_token))
    )
    if registro is None or registro.revogado:
        raise erro
    if _as_utc(registro.expira_em) <= datetime.now(UTC):
        raise erro
    return registro


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str:
    registro = await _carregar_refresh_valido(db, refresh_token)

    usuario = await db.get(Usuario, registro.id_usuario)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido ou expirado.",
        )

    return create_access_token(usuario.id_usuario, usuario.papel)


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    registro = await _carregar_refresh_valido(db, refresh_token)
    registro.revogado = True
    await db.commit()
    logger.info("refresh token revogado id_usuario=%s", registro.id_usuario)
