from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# UC03 não prevê execuções concorrentes do mesmo modelo. A verificação no serviço
# dá a mensagem boa; este índice é quem garante a regra sob concorrência, porque
# dois POST simultâneos passariam os dois pela verificação.
_STATUS_ATIVOS_SQL = "status IN ('pendente', 'processando')"


class Execucao(Base):
    __tablename__ = "execucoes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pendente', 'processando', 'concluida', 'erro')",
            name="ck_execucoes_status",
        ),
        Index(
            "uq_execucoes_ativa_por_modelo",
            "id_modelo",
            unique=True,
            postgresql_where=text(_STATUS_ATIVOS_SQL),
            sqlite_where=text(_STATUS_ATIVOS_SQL),
        ),
    )

    id_execucao: Mapped[int] = mapped_column(primary_key=True)
    id_modelo: Mapped[int] = mapped_column(ForeignKey("modelos_analise.id_modelo"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pendente")
    iniciado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
