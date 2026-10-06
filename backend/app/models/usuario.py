from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.empresa import Empresa


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint("papel IN ('admin', 'usuario_pme')", name="ck_usuarios_papel"),
        CheckConstraint("papel_empresa IN ('dono', 'membro')", name="ck_usuarios_papel_empresa"),
    )

    id_usuario: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Papel GLOBAL da plataforma. Independe da empresa: `papel_empresa` é que diz o
    # que a pessoa pode fazer dentro dela.
    papel: Mapped[str] = mapped_column(String(20), nullable=False, server_default="usuario_pme")
    id_empresa: Mapped[int] = mapped_column(
        ForeignKey("empresas.id_empresa"), nullable=False, index=True
    )
    papel_empresa: Mapped[str] = mapped_column(String(10), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # `joined`: toda carga de usuário (inclusive o `db.get` do token) já traz o nome
    # da empresa, que o cabeçalho mostra — sem lazy load, que o async não permite.
    empresa: Mapped[Empresa] = relationship(lazy="joined")
