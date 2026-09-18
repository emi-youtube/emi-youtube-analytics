from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ModeloAnalise(Base):
    __tablename__ = "modelos_analise"

    id_modelo: Mapped[int] = mapped_column(primary_key=True)
    id_usuario: Mapped[int] = mapped_column(ForeignKey("usuarios.id_usuario"), nullable=False)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    termo_pesquisa: Mapped[str] = mapped_column(String(255), nullable=False)
    filtros: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())
