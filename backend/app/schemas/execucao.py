"""Schemas da execução de análise (UC03/UC04)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExecucaoCreate(BaseModel):
    """O corpo traz só o modelo: todo o resto da execução é derivado dele."""

    id_modelo: int


class ExecucaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_execucao: int
    id_modelo: int
    status: str
    iniciado_em: datetime | None
    concluido_em: datetime | None
