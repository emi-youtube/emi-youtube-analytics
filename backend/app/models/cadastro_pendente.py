from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CadastroPendente(Base):
    """Cadastro de empresa nova à espera da confirmação do e-mail (ADR-014).

    A conta só nasce quando a pessoa abre o link: até lá os dados ficam aqui, fora de
    USUARIOS. Assim o cadastro responde igual tenha o e-mail conta ou não, e ninguém
    "ocupa" o e-mail de outra pessoa. Um pedido por e-mail: um novo substitui o
    anterior. Tabela de infraestrutura, fora do DER; as vencidas saem na escrita
    (regra 7).
    """

    __tablename__ = "cadastros_pendentes"

    id_cadastro: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    nome_empresa: Mapped[str] = mapped_column(String(120), nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # A versão dos termos que a pessoa aceitou ao preencher, gravada no aceite quando
    # a conta nasce: se a versão vigente mudar no meio, o aceite continua verdadeiro.
    versao_termos: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
