"""Schemas de entrada/saída da autenticação.

A senha usa `SecretStr` de propósito: o repr vira `**********`, então ela não
aparece em log, traceback nem em mensagem de erro de validação do Pydantic.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.core.security import MAX_PASSWORD_BYTES

SENHA_MIN_CARACTERES = 8


class UserRegister(BaseModel):
    nome: str = Field(min_length=1, max_length=255)
    email: EmailStr = Field(max_length=255)
    senha: SecretStr

    @field_validator("senha")
    @classmethod
    def validar_senha(cls, valor: SecretStr) -> SecretStr:
        bruta = valor.get_secret_value()
        if len(bruta) < SENHA_MIN_CARACTERES:
            raise ValueError(f"A senha deve ter ao menos {SENHA_MIN_CARACTERES} caracteres.")
        if len(bruta.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"A senha deve ter no máximo {MAX_PASSWORD_BYTES} bytes.")
        return valor


class UserLogin(BaseModel):
    email: EmailStr
    senha: SecretStr


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    """Resposta pública do usuário — nunca inclui `senha_hash`."""

    model_config = ConfigDict(from_attributes=True)

    id_usuario: int
    nome: str
    email: str
    papel: str
    criado_em: datetime


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
