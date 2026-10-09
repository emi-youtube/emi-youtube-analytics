"""Administração da plataforma: só o papel global `admin` (ADR-011, ADR-015).

O router inteiro exige `requer_admin`: uma rota nova aqui nasce restrita por estar
no lugar certo. 403 para quem não é admin, sem esconder a existência da rota, porque
não há recurso de outra empresa sendo protegido por id.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import requer_admin
from app.core.database import get_db
from app.schemas.admin import CotaAdmin
from app.services import cota
from app.services.cota import DIAS_DE_HISTORICO

router = APIRouter(prefix="/admin", dependencies=[Depends(requer_admin)])

Sessao = Annotated[AsyncSession, Depends(get_db)]


@router.get("/cota-youtube", response_model=CotaAdmin)
async def cota_youtube(
    db: Sessao,
    # O histórico guarda 35 dias (regra 7): pedir mais devolveria zeros inventados.
    dias: Annotated[int, Query(ge=1, le=DIAS_DE_HISTORICO)] = 30,
) -> CotaAdmin:
    """O consumo da cota da YouTube API hoje, por empresa, e o histórico do projeto."""
    return await cota.resumo_admin(db, dias)
