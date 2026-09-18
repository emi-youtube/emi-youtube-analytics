from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobDlq(Base):
    """Dead-letter queue: jobs que esgotaram as tentativas em `jobs`."""

    __tablename__ = "jobs_dlq"
    __table_args__ = (
        CheckConstraint("tipo IN ('coleta', 'inferencia', 'topicos')", name="ck_jobs_dlq_tipo"),
    )

    # Não é FK para jobs.id_job: o job original pode já não existir; aqui só arquivamos o histórico.
    id_job: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    id_execucao: Mapped[int] = mapped_column(ForeignKey("execucoes.id_execucao"), nullable=False)
    erro: Mapped[str] = mapped_column(Text, nullable=False)
    falhou_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
