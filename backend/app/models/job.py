from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Job(Base):
    """Fila de jobs (coleta/inferência/tópicos), consumida via SELECT ... FOR UPDATE SKIP LOCKED."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("tipo IN ('coleta', 'inferencia', 'topicos')", name="ck_jobs_tipo"),
        CheckConstraint(
            "status IN ('pendente', 'processando', 'concluida', 'erro')", name="ck_jobs_status"
        ),
    )

    id_job: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    id_execucao: Mapped[int] = mapped_column(ForeignKey("execucoes.id_execucao"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pendente")
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
