from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tema(Base):
    __tablename__ = "temas"

    id_tema: Mapped[int] = mapped_column(primary_key=True)
    id_execucao: Mapped[int] = mapped_column(ForeignKey("execucoes.id_execucao"), nullable=False)
    rotulo_tema: Mapped[str] = mapped_column(String(255), nullable=False)
    # Continua JSONB no Postgres; o variant só permite que o SQLite dos testes
    # (que não tem JSONB) crie a tabela. Não muda o schema real.
    palavras_chave: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
