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
from app.services import permissao

# A dependency no router inteiro: nenhuma rota nova entra aqui sem autenticação.
router = APIRouter(
    prefix="/modelos-analise",
    dependencies=[Depends(get_usuario_atual)],
)

UsuarioAtual = Annotated[Usuario, Depends(get_usuario_atual)]
Sessao = Annotated[AsyncSession, Depends(get_db)]


def _resposta(modelo: ModeloAnalise, usuario: Usuario) -> ModeloAnaliseResponse:
    """O modelo como QUEM PERGUNTA o vê: com o nome do autor e se pode alterá-lo."""
    return ModeloAnaliseResponse(
        id_modelo=modelo.id_modelo,
        id_usuario=modelo.id_usuario,
        id_empresa=modelo.id_empresa,
        nome=modelo.nome,
        termo_pesquisa=modelo.termo_pesquisa,
        filtros=modelo.filtros,
        criado_em=modelo.criado_em,
        autor_nome=modelo.autor.nome,
        pode_alterar=permissao.pode_alterar_modelo(usuario, modelo),
    )


@router.post("", response_model=ModeloAnaliseResponse, status_code=status.HTTP_201_CREATED)
async def criar(
    dados: ModeloAnaliseCreate, usuario: UsuarioAtual, db: Sessao
) -> ModeloAnaliseResponse:
    return _resposta(await service.create(db, usuario, dados), usuario)


@router.get("", response_model=list[ModeloAnaliseResponse])
async def listar(usuario: UsuarioAtual, db: Sessao) -> list[ModeloAnaliseResponse]:
    return [_resposta(m, usuario) for m in await service.list_for_user(db, usuario)]


@router.get("/{id_modelo}", response_model=ModeloAnaliseResponse)
async def detalhar(id_modelo: int, usuario: UsuarioAtual, db: Sessao) -> ModeloAnaliseResponse:
    return _resposta(await service.get_owned(db, usuario, id_modelo), usuario)


@router.patch("/{id_modelo}", response_model=ModeloAnaliseResponse)
async def atualizar(
    id_modelo: int, dados: ModeloAnaliseUpdate, usuario: UsuarioAtual, db: Sessao
) -> ModeloAnaliseResponse:
    return _resposta(await service.update(db, usuario, id_modelo, dados), usuario)


@router.delete("/{id_modelo}", status_code=status.HTTP_204_NO_CONTENT)
async def remover(id_modelo: int, usuario: UsuarioAtual, db: Sessao) -> None:
    await service.delete(db, usuario, id_modelo)
