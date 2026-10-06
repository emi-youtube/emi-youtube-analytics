"""`/api/v1/empresa` — membros e convites da empresa de quem está logado (ADR-011)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_usuario_atual, requer_dono
from app.core.database import get_db
from app.models.convite import Convite
from app.models.usuario import Usuario
from app.schemas.empresa import (
    ConviteCreate,
    ConviteCriadoResponse,
    ConviteResponse,
    MembroResponse,
)
from app.services import email as email_service
from app.services import empresa as service

# Autenticação no router inteiro; gerência (convites, remoção) exige dono por rota.
router = APIRouter(prefix="/empresa", dependencies=[Depends(get_usuario_atual)])

UsuarioAtual = Annotated[Usuario, Depends(get_usuario_atual)]
Dono = Annotated[Usuario, Depends(requer_dono)]
Sessao = Annotated[AsyncSession, Depends(get_db)]


@router.get("/membros", response_model=list[MembroResponse])
async def listar_membros(usuario: UsuarioAtual, db: Sessao) -> list[Usuario]:
    """Qualquer membro vê quem está na empresa; só o dono age sobre a lista."""
    return list(await service.listar_membros(db, usuario))


@router.delete("/membros/{id_usuario}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_membro(id_usuario: int, dono: Dono, db: Sessao) -> None:
    await service.remover_membro(db, dono, id_usuario)


@router.get("/convites", response_model=list[ConviteResponse])
async def listar_convites(dono: Dono, db: Sessao) -> list[Convite]:
    return list(await service.listar_convites(db, dono))


@router.post("/convites", response_model=ConviteCriadoResponse, status_code=status.HTTP_201_CREATED)
async def criar_convite(
    dados: ConviteCreate, dono: Dono, db: Sessao, tarefas: BackgroundTasks
) -> ConviteCriadoResponse:
    """Gera o convite e o envia por e-mail. O link volta aqui UMA vez, para o dono
    poder mandar por outro canal se o e-mail não chegar."""
    nome_empresa = dono.empresa.nome
    convite, token = await service.criar_convite(db, dono, dados)
    assunto, texto = service.email_convite(nome_empresa, token)
    tarefas.add_task(email_service.enviar, convite.email, assunto, texto)
    return ConviteCriadoResponse(
        id_convite=convite.id_convite,
        email=convite.email,
        papel_empresa=convite.papel_empresa,
        expira_em=convite.expira_em,
        criado_em=convite.criado_em,
        link=service.link_convite(token),
    )


@router.delete("/convites/{id_convite}", status_code=status.HTTP_204_NO_CONTENT)
async def revogar_convite(id_convite: int, dono: Dono, db: Sessao) -> None:
    await service.revogar_convite(db, dono, id_convite)
