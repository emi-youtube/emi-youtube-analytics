from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_usuario_atual
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.auth import (
    AccessTokenResponse,
    RefreshRequest,
    TokenPairResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth")


@router.post("/registrar", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def registrar(
    dados: UserRegister,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Usuario:
    return await auth_service.register_user(db, dados)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    dados: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPairResponse:
    usuario = await auth_service.authenticate(db, dados.email, dados.senha.get_secret_value())
    access_token, refresh_token = await auth_service.issue_token_pair(db, usuario)
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    dados: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccessTokenResponse:
    access_token = await auth_service.refresh_access_token(db, dados.refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    dados: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await auth_service.revoke_refresh_token(db, dados.refresh_token)


@router.get("/eu", response_model=UserResponse)
async def eu(usuario: Annotated[Usuario, Depends(get_usuario_atual)]) -> Usuario:
    return usuario
