from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnaliseSentimento(Base):
    __tablename__ = "analises_sentimento"
    __table_args__ = (
        CheckConstraint(
            "sentimento IN ('positivo', 'negativo', 'neutro')",
            name="ck_analises_sentimento_sentimento",
        ),
    )

    id_analise: Mapped[int] = mapped_column(primary_key=True)
    id_comentario: Mapped[int] = mapped_column(
        ForeignKey("comentarios.id_comentario", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    id_versao_modelo: Mapped[int] = mapped_column(
        ForeignKey("versoes_modelo.id_versao"), nullable=False
    )
    sentimento: Mapped[str] = mapped_column(String(20), nullable=False)
    tema: Mapped[str | None] = mapped_column(String(255), nullable=True)
    justificativa: Mapped[str | None] = mapped_column(Text, nullable=True)
    processado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
