from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_usuario_atual
from app.core.database import get_db
from app.models.execucao import Execucao
from app.models.usuario import Usuario
from app.schemas.execucao import ExecucaoCreate, ExecucaoResponse
from app.services import execucao as service

# A dependency no router inteiro: nenhuma rota nova entra aqui sem autenticação.
router = APIRouter(
    prefix="/execucoes",
    dependencies=[Depends(get_usuario_atual)],
)

UsuarioAtual = Annotated[Usuario, Depends(get_usuario_atual)]
Sessao = Annotated[AsyncSession, Depends(get_db)]


@router.post("", response_model=ExecucaoResponse, status_code=status.HTTP_202_ACCEPTED)
async def criar(dados: ExecucaoCreate, usuario: UsuarioAtual, db: Sessao) -> Execucao:
    """202 Accepted: a execução foi aceita e enfileirada, não executada.

    Quem chama acompanha o andamento por GET /execucoes/{id} (UC04).
    """
    return await service.create(db, usuario, dados)


@router.get("", response_model=list[ExecucaoResponse])
async def listar(usuario: UsuarioAtual, db: Sessao) -> list[Execucao]:
    return list(await service.list_for_user(db, usuario))


@router.get("/{id_execucao}", response_model=ExecucaoResponse)
async def detalhar(id_execucao: int, usuario: UsuarioAtual, db: Sessao) -> Execucao:
    return await service.get_owned(db, usuario, id_execucao)
