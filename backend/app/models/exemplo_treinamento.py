from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExemploTreinamento(Base):
    """Exemplo do corpus de treino.

    `split` nulo = partição ainda não atribuída. A atribuição acontece DEPOIS da
    rotulagem fraca: sortear a partição junto da exportação faria o conjunto de
    teste nascer dentro do corpus de rótulo fraco, e a avaliação viraria circular
    (CLAUDE.md regra 6 — o teste é só humano).
    """

    __tablename__ = "exemplos_treinamento"
    # O CHECK vale só para os valores não nulos: `NULL IN (...)` avalia para NULL,
    # e CHECK só reprova em FALSE.
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
    split: Mapped[str | None] = mapped_column(String(20), nullable=True)
