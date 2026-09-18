from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ModeloAnalise(Base):
    __tablename__ = "modelos_analise"

    id_modelo: Mapped[int] = mapped_column(primary_key=True)
    id_usuario: Mapped[int] = mapped_column(ForeignKey("usuarios.id_usuario"), nullable=False)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    termo_pesquisa: Mapped[str] = mapped_column(String(255), nullable=False)
    # Continua JSONB no Postgres; o variant só permite que o SQLite dos testes
    # (que não tem JSONB) crie a tabela. Não muda o schema real.
    filtros: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
