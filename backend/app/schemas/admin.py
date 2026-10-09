"""Schemas da área de administração da plataforma (papel global `admin`)."""

from datetime import date, datetime

from pydantic import BaseModel


class CotaDaEmpresa(BaseModel):
    """Uma linha da tabela "Cota por empresa"."""

    id_empresa: int
    nome: str
    unidades_hoje: int
    # Soma do período pedido (`dias`), hoje incluído.
    unidades_periodo: int
    # Execuções paradas agora esperando a renovação da cota (ADR-015).
    execucoes_aguardando: int
    # Gastou hoje mais que a fatia garantida: é quem para primeiro quando o dia passa
    # da folga compartilhada.
    acima_da_fatia: bool


class ConsumoDoDia(BaseModel):
    dia: date
    unidades: int


class CotaAdmin(BaseModel):
    """`GET /admin/cota-youtube`: o dia de hoje, por empresa, e o histórico do projeto."""

    dia_da_cota: date
    renova_em: datetime
    limite: int
    reserva: int
    fatia_por_empresa: int
    # Até quantas unidades do dia vale a folga compartilhada (70% do limite, por padrão).
    teto_folga: int
    usado_hoje: int
    # Unidades que a API disse já não existirem sem o app as ter gasto (linha de ajuste).
    ajuste_hoje: int
    dias: int
    empresas: list[CotaDaEmpresa]
    # Um ponto por dia do período, do mais antigo ao de hoje, com zero nos dias sem uso.
    historico: list[ConsumoDoDia]
    pico_no_periodo: int
    media_no_periodo: float
