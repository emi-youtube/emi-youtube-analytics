from datetime import date

from sqlalchemy import Date, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# `id_empresa` com este valor guarda o AJUSTE: unidades que o app não gastou mas a API
# disse que já não existem (cota gasta por fora, ou contagem atrasada). Ver
# `services/cota.marcar_esgotada`.
ID_AJUSTE = 0


class UsoCotaYoutube(Base):
    """Unidades da cota da YouTube Data API gastas por empresa em cada dia (ADR-015).

    O dia é o da COTA, o do fuso do Pacífico (a API zera à meia-noite de lá), e não o
    de Brasília. Tabela de infraestrutura, fora do DER: existe para o app decidir se
    pode coletar sem bater na API e para o cartão "Cota do YouTube hoje".

    `id_empresa` SEM chave estrangeira, de propósito: excluir a empresa não pode
    devolver à conta do dia unidades que a API já cobrou. O que fica é um número por
    dia, sem dado pessoal. Cresce no máximo uma linha por empresa por dia; as de mais
    de 35 dias saem na própria escrita (regra 7 do CLAUDE.md).
    """

    __tablename__ = "uso_cota_youtube"

    dia: Mapped[date] = mapped_column(Date, primary_key=True)
    id_empresa: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    unidades: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
