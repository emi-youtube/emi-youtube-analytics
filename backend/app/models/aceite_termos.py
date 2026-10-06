from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AceiteTermos(Base):
    """Registro de que a pessoa aceitou uma versão dos Termos e da Política (ADR-012).

    Uma linha por versão aceita: o histórico fica, e a versão vigente
    (`VERSAO_TERMOS`) é a que decide se ainda há aceite pendente. Sai com o usuário
    (CASCADE): o registro prova o aceite de quem tem conta, e quem excluiu a conta não
    tem mais relação a provar.
    """

    __tablename__ = "aceites_termos"
    __table_args__ = (
        # Um aceite por versão (idempotência); serve também de índice por `id_usuario`.
        UniqueConstraint("id_usuario", "versao_termos", name="uq_aceites_termos_usuario_versao"),
    )

    id_aceite: Mapped[int] = mapped_column(primary_key=True)
    id_usuario: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id_usuario", ondelete="CASCADE"), nullable=False
    )
    versao_termos: Mapped[str] = mapped_column(String(20), nullable=False)
    aceito_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
