from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Comentario(Base):
    __tablename__ = "comentarios"

    id_comentario: Mapped[int] = mapped_column(primary_key=True)
    id_video: Mapped[int] = mapped_column(
        ForeignKey("videos.id_video", ondelete="CASCADE"), nullable=False
    )
    youtube_comment_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # SHA-256 do autor original — nunca persistir nome/ID real (LGPD, ver CLAUDE.md regra 2)
    autor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
