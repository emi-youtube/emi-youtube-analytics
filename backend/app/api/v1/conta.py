"""`/api/v1/conta` — aceite dos termos e direitos do titular sobre a própria conta."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_usuario_atual
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.conta import ExcluirContaRequest, MeusDadosResponse
from app.services import conta as service
from app.services import termos as termos_service

router = APIRouter(prefix="/conta")

UsuarioAtual = Annotated[Usuario, Depends(get_usuario_atual)]
Sessao = Annotated[AsyncSession, Depends(get_db)]


@router.post("/aceitar-termos", status_code=status.HTTP_204_NO_CONTENT)
async def aceitar_termos(usuario: UsuarioAtual, db: Sessao) -> None:
    """Aceite da versão vigente por quem já tem conta. Idempotente."""
    await termos_service.aceitar(db, usuario.id_usuario)


@router.get("/meus-dados", response_model=MeusDadosResponse)
async def meus_dados(usuario: UsuarioAtual, db: Sessao) -> MeusDadosResponse:
    dados = await service.meus_dados(db, usuario)
    return MeusDadosResponse(
        nome=usuario.nome,
        email=usuario.email,
        empresa={"nome": usuario.empresa.nome},
        papel=usuario.papel,
        papel_empresa=usuario.papel_empresa,
        criado_em=usuario.criado_em,
        aceites_termos=dados.aceites,
        modelos_criados=dados.modelos,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def excluir_conta(dados: ExcluirContaRequest, usuario: UsuarioAtual, db: Sessao) -> None:
    """Exclui a conta (e, se for o dono único, a empresa). Corpo: a senha atual.

    401 senha errada · 409 dono com membros ou análise em andamento · 429 bloqueado.
    """
    await service.excluir_conta(db, usuario, dados.senha.get_secret_value())
