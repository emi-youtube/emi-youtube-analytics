from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Execucao(Base):
    __tablename__ = "execucoes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pendente', 'processando', 'concluida', 'erro')",
            name="ck_execucoes_status",
        ),
    )

    id_execucao: Mapped[int] = mapped_column(primary_key=True)
    id_modelo: Mapped[int] = mapped_column(ForeignKey("modelos_analise.id_modelo"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pendente")
    iniciado_em: Mapped[datetime | None] = mapped_column(nullable=True)
    concluido_em: Mapped[datetime | None] = mapped_column(nullable=True)
