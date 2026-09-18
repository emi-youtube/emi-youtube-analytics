from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExemploTreinamento(Base):
    __tablename__ = "exemplos_treinamento"
    __table_args__ = (
        CheckConstraint(
            "split IN ('treino', 'validacao', 'teste')", name="ck_exemplos_treinamento_split"
        ),
    )

    id_exemplo: Mapped[int] = mapped_column(primary_key=True)
    # Nullable: exemplo pode sobreviver à exclusão do comentário de origem (ver ondelete)
    id_comentario: Mapped[int | None] = mapped_column(
        ForeignKey("comentarios.id_comentario", ondelete="SET NULL"), nullable=True
    )
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    rotulo_fraco: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rotulo_humano: Mapped[str | None] = mapped_column(String(20), nullable=True)
    split: Mapped[str] = mapped_column(String(20), nullable=False)
