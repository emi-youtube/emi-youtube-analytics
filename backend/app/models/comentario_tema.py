from sqlalchemy import Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ComentarioTema(Base):
    """Relação N:N entre comentários e temas, com o peso do tema no comentário."""

    __tablename__ = "comentario_tema"

    id_comentario: Mapped[int] = mapped_column(
        ForeignKey("comentarios.id_comentario", ondelete="CASCADE"), primary_key=True
    )
    id_tema: Mapped[int] = mapped_column(
        ForeignKey("temas.id_tema", ondelete="CASCADE"), primary_key=True
    )
    peso: Mapped[float] = mapped_column(Float, nullable=False)
