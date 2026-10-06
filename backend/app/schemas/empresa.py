"""Schemas da gestão da empresa: membros e convites."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

PapelEmpresa = Literal["dono", "membro"]


class MembroResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_usuario: int
    nome: str
    email: str
    papel_empresa: str
    criado_em: datetime


class ConviteCreate(BaseModel):
    email: EmailStr = Field(max_length=255)
    papel_empresa: PapelEmpresa = "membro"


class ConviteResponse(BaseModel):
    """Convite pendente, como a tela do dono lista. Nunca traz o token."""

    model_config = ConfigDict(from_attributes=True)

    id_convite: int
    email: str
    papel_empresa: str
    expira_em: datetime
    criado_em: datetime


class ConviteCriadoResponse(ConviteResponse):
    """Resposta da criação: a ÚNICA vez em que o link com o token aparece.

    O banco só tem o hash; perdeu o link, revogue e gere outro.
    """

    link: str
