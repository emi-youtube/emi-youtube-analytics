"""Schemas do modelo de análise (UC02)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FiltrosModelo(BaseModel):
    """Filtros da coleta. Vai para uma coluna JSONB, então aceita chaves extras:
    a dupla de coleta ainda vai acrescentar filtros sem precisar de migration.
    """

    model_config = ConfigDict(extra="allow")

    # Os vídeos são curados manualmente (CLAUDE.md regra 4): são eles que
    # definem o escopo da coleta, e o worker lê exatamente esta chave.
    videos: list[str] = Field(default_factory=list)
    canais: list[str] = Field(default_factory=list)

    @field_validator("videos", "canais")
    @classmethod
    def limpar_lista(cls, valor: list[str]) -> list[str]:
        """Descarta entradas em branco — senão `videos: [""]` passaria pela regra
        do UC02 como se um vídeo tivesse sido informado.
        """
        return [item.strip() for item in valor if item.strip()]


def _validar_nome(valor: str) -> str:
    limpo = valor.strip()
    if not limpo:
        raise ValueError("O nome não pode ser vazio.")
    return limpo


class ModeloAnaliseCreate(BaseModel):
    nome: str = Field(max_length=255)
    termo_pesquisa: str = Field(default="", max_length=255)
    filtros: FiltrosModelo | None = None

    _nome_valido = field_validator("nome")(_validar_nome)

    @field_validator("termo_pesquisa")
    @classmethod
    def limpar_termo(cls, valor: str) -> str:
        return valor.strip()


class ModeloAnaliseUpdate(BaseModel):
    """PATCH: só os campos enviados são alterados (`exclude_unset`)."""

    nome: str | None = Field(default=None, max_length=255)
    termo_pesquisa: str | None = Field(default=None, max_length=255)
    filtros: FiltrosModelo | None = None

    @field_validator("nome")
    @classmethod
    def validar_nome(cls, valor: str | None) -> str | None:
        return None if valor is None else _validar_nome(valor)

    @field_validator("termo_pesquisa")
    @classmethod
    def limpar_termo(cls, valor: str | None) -> str | None:
        return None if valor is None else valor.strip()


class ModeloAnaliseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_modelo: int
    id_usuario: int
    nome: str
    termo_pesquisa: str
    filtros: dict | None
    criado_em: datetime
