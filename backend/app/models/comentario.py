from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Comentario(Base):
    __tablename__ = "comentarios"
    # Unicidade por VIDEO (que já é por execução), pelo mesmo motivo de VIDEOS.
    __table_args__ = (
        UniqueConstraint("id_video", "youtube_comment_id", name="uq_comentarios_video_comentario"),
    )

    id_comentario: Mapped[int] = mapped_column(primary_key=True)
    id_video: Mapped[int] = mapped_column(
        ForeignKey("videos.id_video", ondelete="CASCADE"), nullable=False
    )
    # Os três abaixo ficam NULOS depois do expurgo de 30 dias (ADR-015, políticas dos
    # YouTube API Services III.E.4.d): o texto e a identificação vêm da API e não podem
    # ficar guardados; a linha fica, porque a análise e o tema penduram nela.
    youtube_comment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # SHA-256 do autor original — nunca persistir nome/ID real (LGPD, ver CLAUDE.md regra 2)
    autor_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
