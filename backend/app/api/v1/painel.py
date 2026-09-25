"""`GET /api/v1/painel` — a tela Início num endpoint só."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_usuario_atual
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.painel import ResumoPainel
from app.services import painel as service

router = APIRouter(dependencies=[Depends(get_usuario_atual)])

UsuarioAtual = Annotated[Usuario, Depends(get_usuario_atual)]
Sessao = Annotated[AsyncSession, Depends(get_db)]


@router.get("/painel", response_model=ResumoPainel)
async def resumo(usuario: UsuarioAtual, db: Sessao) -> ResumoPainel:
    """Resumo do usuário do token. Nunca 404: conta nova devolve painel vazio."""
    return await service.resumo(db, usuario)
