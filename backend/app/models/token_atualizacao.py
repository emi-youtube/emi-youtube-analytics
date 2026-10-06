from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TokenAtualizacao(Base):
    """Refresh tokens emitidos, para permitir revogação (UC01)."""

    __tablename__ = "tokens_atualizacao"

    id_token: Mapped[int] = mapped_column(primary_key=True)
    id_usuario: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id_usuario", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 do token: o banco nunca guarda o valor utilizável
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revogado: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # Rotação: cada /auth/refresh troca o token por um novo e carimba o antigo aqui.
    # Diferente de `revogado` (logout, troca de senha): um token SUBSTITUÍDO que
    # reaparece só pode ser cópia — o dono legítimo já recebeu o sucessor — e por
    # isso derruba todos os tokens do usuário (detecção de reuso).
    substituido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
