from sqlalchemy import CheckConstraint, String
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
    metricas_avaliacao: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ativo")
