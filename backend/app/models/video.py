from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Video(Base):
    __tablename__ = "videos"
    # Unicidade por EXECUCAO, não global: o mesmo vídeo pode ser analisado de novo
    # numa execução posterior, e por outro usuário — VIDEOS é o retrato daquela
    # coleta (por isso a exclusão da execução leva os vídeos junto).
    __table_args__ = (
        UniqueConstraint("id_execucao", "youtube_video_id", name="uq_videos_execucao_video"),
    )

    id_video: Mapped[int] = mapped_column(primary_key=True)
    id_execucao: Mapped[int] = mapped_column(
        ForeignKey("execucoes.id_execucao", ondelete="CASCADE"), nullable=False
    )
    youtube_video_id: Mapped[str] = mapped_column(String(32), nullable=False)
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    canal: Mapped[str] = mapped_column(String(255), nullable=False)
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visualizacoes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    curtidas: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
