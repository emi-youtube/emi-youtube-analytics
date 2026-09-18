from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_usuario_atual
from app.core.database import get_db
from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario
from app.schemas.modelo_analise import (
    ModeloAnaliseCreate,
    ModeloAnaliseResponse,
    ModeloAnaliseUpdate,
)
from app.services import modelo_analise as service

# A dependency no router inteiro: nenhuma rota nova entra aqui sem autenticação.
router = APIRouter(
    prefix="/modelos-analise",
    dependencies=[Depends(get_usuario_atual)],
)

UsuarioAtual = Annotated[Usuario, Depends(get_usuario_atual)]
Sessao = Annotated[AsyncSession, Depends(get_db)]


@router.post("", response_model=ModeloAnaliseResponse, status_code=status.HTTP_201_CREATED)
async def criar(
    dados: ModeloAnaliseCreate, usuario: UsuarioAtual, db: Sessao
) -> ModeloAnalise:
    return await service.create(db, usuario, dados)


@router.get("", response_model=list[ModeloAnaliseResponse])
async def listar(usuario: UsuarioAtual, db: Sessao) -> list[ModeloAnalise]:
    return list(await service.list_for_user(db, usuario))


@router.get("/{id_modelo}", response_model=ModeloAnaliseResponse)
async def detalhar(id_modelo: int, usuario: UsuarioAtual, db: Sessao) -> ModeloAnalise:
    return await service.get_owned(db, usuario, id_modelo)


@router.patch("/{id_modelo}", response_model=ModeloAnaliseResponse)
async def atualizar(
    id_modelo: int, dados: ModeloAnaliseUpdate, usuario: UsuarioAtual, db: Sessao
) -> ModeloAnalise:
    return await service.update(db, usuario, id_modelo, dados)


@router.delete("/{id_modelo}", status_code=status.HTTP_204_NO_CONTENT)
async def remover(id_modelo: int, usuario: UsuarioAtual, db: Sessao) -> None:
    await service.delete(db, usuario, id_modelo)
