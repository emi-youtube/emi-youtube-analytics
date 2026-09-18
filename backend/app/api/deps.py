"""Dependencies de autenticação e autorização."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import TOKEN_TYPE_ACCESS, decode_token
from app.models.usuario import Usuario
from app.services.auth import PAPEL_ADMIN

# auto_error=False para responder 401 (e não o 403 padrão do HTTPBearer) quando
# o cabeçalho Authorization não vem.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_usuario_atual(
    credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Usuario:
    nao_autenticado = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não autenticado.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credenciais is None:
        raise nao_autenticado

    payload = decode_token(credenciais.credentials, TOKEN_TYPE_ACCESS)
    if payload is None:
        raise nao_autenticado

    usuario = await db.get(Usuario, int(payload["sub"]))
    if usuario is None:
        raise nao_autenticado

    return usuario


async def requer_admin(
    usuario: Annotated[Usuario, Depends(get_usuario_atual)],
) -> Usuario:
    if usuario.papel != PAPEL_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores.",
        )
    return usuario
