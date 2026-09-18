from sqlalchemy import JSON, CheckConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VersaoModelo(Base):
    __tablename__ = "versoes_modelo"
    __table_args__ = (
        CheckConstraint("status IN ('ativo', 'arquivado')", name="ck_versoes_modelo_status"),
    )

    id_versao: Mapped[int] = mapped_column(primary_key=True)
    nome_modelo: Mapped[str] = mapped_column(String(255), nullable=False)
    versao: Mapped[str] = mapped_column(String(50), nullable=False)
    # Continua JSONB no Postgres; o variant só permite que o SQLite dos testes
    # (que não tem JSONB) crie a tabela. Não muda o schema real.
    metricas_avaliacao: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ativo")
