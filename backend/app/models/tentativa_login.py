from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TentativaLogin(Base):
    """Registra apenas tentativas de login MALSUCEDIDAS, para o bloqueio do UC01.

    A tentativa é gravada mesmo quando a conta não existe: se só registrássemos
    e-mails cadastrados, o próprio bloqueio viraria um oráculo de existência de conta.
    Em login bem-sucedido as linhas daquele e-mail são apagadas (reset do contador).

    Grava `email_hash` (SHA-256), nunca o e-mail em texto plano: a tabela registra
    tentativas de quem nem tem conta, e o bloqueio só precisa comparar igualdade.
    """

    __tablename__ = "tentativas_login"
    __table_args__ = (
        Index("ix_tentativas_login_email_hash_tentado_em", "email_hash", "tentado_em"),
    )

    id_tentativa: Mapped[int] = mapped_column(primary_key=True)
    # 64 caracteres: SHA-256 em hexadecimal.
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tentado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
