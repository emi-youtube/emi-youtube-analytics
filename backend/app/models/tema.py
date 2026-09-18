from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tema(Base):
    __tablename__ = "temas"

    id_tema: Mapped[int] = mapped_column(primary_key=True)
    id_execucao: Mapped[int] = mapped_column(ForeignKey("execucoes.id_execucao"), nullable=False)
    rotulo_tema: Mapped[str] = mapped_column(String(255), nullable=False)
    palavras_chave: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
