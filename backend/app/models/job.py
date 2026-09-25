from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
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
        # Índice do reaper: ele varre por status + reivindicado_em a cada
        # passagem, e sem isto seria varredura da tabela inteira.
        Index("ix_jobs_status_reivindicado_em", "status", "reivindicado_em"),
    )

    id_job: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    id_execucao: Mapped[int] = mapped_column(ForeignKey("execucoes.id_execucao"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pendente")
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Continua JSONB no Postgres; o variant só permite que o SQLite dos testes
    # (que não tem JSONB) crie a tabela. Não muda o schema real.
    payload: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Quando este job foi reivindicado por um worker. É o que distingue "está
    # rodando" de "o worker morreu e abandonou": o reaper devolve à fila o que
    # passou do tempo limite (`workers/fila.devolver_presos`). Nulo enquanto o
    # job está pendente, e nas linhas anteriores à migration 0009.
    reivindicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
