from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Empresa(Base):
    """A unidade de isolamento dos dados (ADR-011, docs/BANCO.md).

    Modelos de análise, execuções e resultados pertencem à empresa, não à pessoa:
    todos os membros enxergam o mesmo, e empresas diferentes nunca se enxergam.
    """

    __tablename__ = "empresas"

    id_empresa: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
