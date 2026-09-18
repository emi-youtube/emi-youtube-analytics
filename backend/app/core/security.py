"""Hash de senha (bcrypt) e emissão/validação de tokens JWT."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt trunca silenciosamente o que passar de 72 bytes; validamos antes para
# não aceitar uma senha longa cujo sufixo seria ignorado na verificação.
MAX_PASSWORD_BYTES = 72

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except ValueError:
        # hash malformado no banco — trata como credencial inválida, sem vazar detalhe
        return False


@lru_cache
def dummy_password_hash() -> str:
    """Hash descartável para equalizar o tempo de resposta quando o e-mail não existe.

    Sem isso, "e-mail inexistente" responderia muito mais rápido que "senha errada",
    e o tempo de resposta viraria um oráculo de existência de conta (UC01).
    """
    return hash_password(uuid.uuid4().hex)


def hash_token(valor: str) -> str:
    """SHA-256 em hexadecimal, usado no refresh token e no e-mail de `tentativas_login`.

    SHA-256 (e não bcrypt) porque o refresh token já é aleatório de alta entropia —
    não há o que proteger contra força bruta de dicionário, e o banco nunca guarda
    o token utilizável.

    Para o e-mail o efeito é outro e menor: tira o dado pessoal em texto plano da
    tabela e mantém a comparação por igualdade que o bloqueio precisa. Não é sigilo
    forte — quem tiver o dump pode testar e-mails suspeitos, já que o espaço é
    enumerável. Serve como minimização de dado, não como proteção criptográfica.
    """
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def create_access_token(id_usuario: int, papel: str) -> str:
    agora = datetime.now(UTC)
    payload = {
        "sub": str(id_usuario),
        "papel": papel,
        "type": TOKEN_TYPE_ACCESS,
        "iat": agora,
        "exp": agora + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(id_usuario: int) -> tuple[str, datetime]:
    """Retorna o token e o instante de expiração (para persistir junto)."""
    agora = datetime.now(UTC)
    expira_em = agora + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": str(id_usuario),
        "type": TOKEN_TYPE_REFRESH,
        "jti": uuid.uuid4().hex,
        "iat": agora,
        "exp": expira_em,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expira_em


def decode_token(token: str, expected_type: str) -> dict | None:
    """Decodifica e valida assinatura, expiração e tipo. `None` se inválido."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload
