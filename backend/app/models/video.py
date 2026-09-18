from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Video(Base):
    __tablename__ = "videos"

    id_video: Mapped[int] = mapped_column(primary_key=True)
    id_execucao: Mapped[int] = mapped_column(
        ForeignKey("execucoes.id_execucao", ondelete="CASCADE"), nullable=False
    )
    youtube_video_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    canal: Mapped[str] = mapped_column(String(255), nullable=False)
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visualizacoes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    curtidas: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
