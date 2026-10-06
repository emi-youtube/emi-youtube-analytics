from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.usuario import Usuario


class ModeloAnalise(Base):
    __tablename__ = "modelos_analise"

    id_modelo: Mapped[int] = mapped_column(primary_key=True)
    # Quem criou o modelo (autoria). A POSSE é da empresa: é por `id_empresa` que
    # toda consulta filtra (app/services/escopo.py).
    id_usuario: Mapped[int] = mapped_column(ForeignKey("usuarios.id_usuario"), nullable=False)
    id_empresa: Mapped[int] = mapped_column(
        ForeignKey("empresas.id_empresa"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    termo_pesquisa: Mapped[str] = mapped_column(String(255), nullable=False)
    # Continua JSONB no Postgres; o variant só permite que o SQLite dos testes
    # (que não tem JSONB) crie a tabela. Não muda o schema real.
    filtros: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # `joined`: a lista de modelos mostra "criado por <nome>" sem uma consulta por
    # linha (o async não permite lazy load). Só leitura: nada em cascata.
    autor: Mapped["Usuario"] = relationship(lazy="joined", viewonly=True)
