from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Convite(Base):
    """Convite de uso único para entrar numa empresa existente.

    Guarda só o SHA-256 do token (como `tokens_atualizacao`): quem tiver o dump do
    banco não consegue usar convite nenhum. O e-mail fica em texto plano porque é
    ele que o cadastro compara e que a tela do dono lista.
    """

    __tablename__ = "convites"
    __table_args__ = (
        CheckConstraint("papel_empresa IN ('dono', 'membro')", name="ck_convites_papel_empresa"),
    )

    id_convite: Mapped[int] = mapped_column(primary_key=True)
    id_empresa: Mapped[int] = mapped_column(
        ForeignKey("empresas.id_empresa", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    papel_empresa: Mapped[str] = mapped_column(String(10), nullable=False)
    # CASCADE: o convite pendente de quem saiu da empresa sai junto com ele.
    criado_por: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id_usuario", ondelete="CASCADE"), nullable=False
    )
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
