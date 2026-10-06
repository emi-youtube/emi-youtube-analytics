"""Schemas de `/api/v1/conta` — direitos do titular (ADR-012)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, SecretStr


class ExcluirContaRequest(BaseModel):
    # Confirmação: um access token roubado não basta para apagar a conta.
    senha: SecretStr


class AceiteResumo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    versao_termos: str
    aceito_em: datetime


class ModeloCriadoResumo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nome: str
    criado_em: datetime


class EmpresaDoTitular(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nome: str


class MeusDadosResponse(BaseModel):
    """Exportação dos dados da pessoa (LGPD, art. 18, II).

    Lista FECHADA de campos, de propósito: um campo novo em `Usuario` (como
    `senha_hash`) não aparece aqui sem alguém escrevê-lo. Não há token, hash de
    credencial nem dado de outro membro.
    """

    nome: str
    email: str
    empresa: EmpresaDoTitular
    papel: str
    papel_empresa: str
    criado_em: datetime
    aceites_termos: list[AceiteResumo]
    modelos_criados: list[ModeloCriadoResumo]
