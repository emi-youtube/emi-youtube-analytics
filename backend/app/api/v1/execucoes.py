from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_usuario_atual
from app.core.database import get_db
from app.models.execucao import Execucao
from app.models.usuario import Usuario
from app.schemas.execucao import ExecucaoCreate, ExecucaoResponse
from app.schemas.resultado import (
    PaginaComentarios,
    ResultadoDisponivel,
    ResultadoExecucao,
    Sentimento,
)
from app.services import execucao as service
from app.services import resultado as service_resultado

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


# ATENÇÃO À ORDEM: esta rota literal vem ANTES de `/{id_execucao}`. O FastAPI
# resolve na ordem de declaração e `{id_execucao}` é `int`, então
# `GET /execucoes/resultados` cairia nela e falharia com 422 "não é inteiro" em
# vez de chegar aqui.
@router.get("/resultados", response_model=list[ResultadoDisponivel])
async def listar_resultados(usuario: UsuarioAtual, db: Sessao) -> list[ResultadoDisponivel]:
    """As execuções CONCLUÍDAS do usuário — a lista da tela de resultados."""
    return await service_resultado.resultados_disponiveis(db, usuario)


@router.get("/{id_execucao}", response_model=ExecucaoResponse)
async def detalhar(id_execucao: int, usuario: UsuarioAtual, db: Sessao) -> Execucao:
    return await service.get_owned(db, usuario, id_execucao)


@router.get("/{id_execucao}/resultado", response_model=ResultadoExecucao)
async def resultado(id_execucao: int, usuario: UsuarioAtual, db: Sessao) -> ResultadoExecucao:
    """A tela Resultados inteira. 404 quando a execução é de outro usuário."""
    return await service_resultado.resultado_da_execucao(db, usuario, id_execucao)


@router.get("/{id_execucao}/comentarios", response_model=PaginaComentarios)
async def comentarios(
    id_execucao: int,
    usuario: UsuarioAtual,
    db: Sessao,
    pagina: Annotated[int, Query(ge=1)] = 1,
    # Teto de 200: a tela pede 5, e um `tamanho` sem limite deixaria um cliente
    # pedir a execução inteira numa resposta só.
    tamanho: Annotated[int, Query(ge=1, le=200)] = 5,
    busca: str | None = None,
    id_tema: int | None = None,
    id_video: int | None = None,
    sentimento: Annotated[Sentimento | None, Query()] = None,
) -> PaginaComentarios:
    """Página de comentários analisados, com os filtros da tela.

    `sentimento` é validado contra os três valores do CHECK: um valor inválido
    responde 422 em vez de devolver página vazia, que pareceria "sem resultado".
    """
    return await service_resultado.pagina_da_execucao(
        db,
        usuario,
        id_execucao,
        pagina=pagina,
        tamanho=tamanho,
        busca=busca,
        id_tema=id_tema,
        id_video=id_video,
        sentimento=sentimento,
    )
