from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TentativaLogin(Base):
    """Registra apenas tentativas de login MALSUCEDIDAS, para o bloqueio do UC01.

    O e-mail é gravado mesmo quando não existe conta: se só registrássemos e-mails
    cadastrados, o próprio bloqueio viraria um oráculo de existência de conta.
    Em login bem-sucedido as linhas do e-mail são apagadas (reset do contador).
    """

    __tablename__ = "tentativas_login"
    __table_args__ = (Index("ix_tentativas_login_email_tentado_em", "email", "tentado_em"),)

    id_tentativa: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    tentado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
