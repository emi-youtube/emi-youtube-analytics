"""Schemas de entrada/saída da autenticação.

A senha usa `SecretStr` de propósito: o repr vira `**********`, então ela não
aparece em log, traceback nem em mensagem de erro de validação do Pydantic.
"""

from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.core.security import MAX_PASSWORD_BYTES

SENHA_MIN_CARACTERES = 8


def validar_forca_senha(valor: SecretStr) -> SecretStr:
    """A política de senha, a mesma no cadastro, na troca e na redefinição."""
    bruta = valor.get_secret_value()
    if len(bruta) < SENHA_MIN_CARACTERES:
        raise ValueError(f"A senha deve ter ao menos {SENHA_MIN_CARACTERES} caracteres.")
    if len(bruta.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"A senha deve ter no máximo {MAX_PASSWORD_BYTES} bytes.")
    return valor


class UserRegister(BaseModel):
    """Cadastro: cria uma empresa (`nome_empresa`) OU entra numa (`token_convite`).

    Exatamente um dos dois. Quem vem por convite não escolhe empresa nem papel —
    os dois vêm do convite.
    """

    nome: str = Field(min_length=1, max_length=255)
    email: EmailStr = Field(max_length=255)
    senha: SecretStr
    nome_empresa: str | None = Field(default=None, max_length=120)
    token_convite: str | None = Field(default=None, max_length=128)
    # Obrigatório e verdadeiro nos dois caminhos (ADR-012): sem o campo, 422 de campo
    # ausente; com `false`, 422 do validador abaixo. O backend grava o aceite da versão
    # vigente — a versão nunca vem do cliente.
    aceite_termos: bool

    @field_validator("senha")
    @classmethod
    def validar_senha(cls, valor: SecretStr) -> SecretStr:
        return validar_forca_senha(valor)

    @field_validator("aceite_termos")
    @classmethod
    def exigir_aceite(cls, valor: bool) -> bool:
        if not valor:
            raise ValueError("É preciso aceitar os Termos de Uso e a Política de Privacidade.")
        return valor

    @field_validator("nome_empresa", "token_convite")
    @classmethod
    def vazio_vira_nulo(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return valor.strip() or None

    @model_validator(mode="after")
    def empresa_ou_convite(self) -> "UserRegister":
        if (self.nome_empresa is None) == (self.token_convite is None):
            raise ValueError(
                "Informe o nome da empresa para criar uma, ou o convite para entrar numa."
            )
        return self


class UserLogin(BaseModel):
    email: EmailStr
    senha: SecretStr


class RefreshRequest(BaseModel):
    refresh_token: str


class TrocarSenhaRequest(BaseModel):
    senha_atual: SecretStr
    nova_senha: SecretStr

    @field_validator("nova_senha")
    @classmethod
    def validar_nova(cls, valor: SecretStr) -> SecretStr:
        return validar_forca_senha(valor)


class EsqueciSenhaRequest(BaseModel):
    email: EmailStr = Field(max_length=255)


class ConfirmarCadastroRequest(BaseModel):
    """O token do link de confirmação do cadastro de empresa nova (ADR-014)."""

    token: str = Field(min_length=1, max_length=128)


class RedefinirSenhaRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    nova_senha: SecretStr

    @field_validator("nova_senha")
    @classmethod
    def validar_nova(cls, valor: SecretStr) -> SecretStr:
        return validar_forca_senha(valor)


class ConsultarConviteRequest(BaseModel):
    # No corpo, e não no caminho da URL: caminho vai para log de acesso.
    token: str = Field(min_length=1, max_length=128)


class ConviteParaCadastroResponse(BaseModel):
    email: str
    nome_empresa: str
    papel_empresa: str


class EmpresaResumo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_empresa: int
    nome: str


class UserResponse(BaseModel):
    """Resposta pública do usuário — nunca inclui `senha_hash`."""

    model_config = ConfigDict(from_attributes=True)

    id_usuario: int
    nome: str
    email: str
    papel: str
    papel_empresa: str
    empresa: EmpresaResumo
    criado_em: datetime


class EuResponse(UserResponse):
    """`GET /auth/eu`: o usuário e se ainda falta aceitar a versão vigente dos termos."""

    termos_pendentes: bool


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MensagemResponse(BaseModel):
    detail: str
