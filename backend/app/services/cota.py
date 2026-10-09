"""Cota diária da YouTube Data API: contar, repartir e esperar (ADR-015).

**O problema.** O Google dá 10.000 unidades por dia por projeto, e a chave é uma só:
todas as empresas dividem o mesmo saldo. Sem controle, uma empresa que dispara muitas
análises zera o dia das outras, e a coleta que bate no limite falha para sempre — a
empresa perde a execução por algo que não é culpa dela.

**A solução tem três peças.**

1. *Contar.* Cada chamada à API soma suas unidades em `uso_cota_youtube`, por empresa e
   por dia da cota (fuso do Pacífico). O cartão "Cota do YouTube hoje" lê daqui.
2. *Repartir.* Antes de coletar, o worker pede o ORÇAMENTO da empresa
   (`orcamento_da_empresa`): cada empresa tem uma fatia garantida e, enquanto o dia
   está abaixo da folga compartilhada, pode usar além dela. Passada a folga, sobra a
   cada uma só o que falta da própria fatia.
3. *Esperar.* Sem orçamento, a coleta não falha: o job é ADIADO até a renovação
   (`proxima_renovacao`) e a execução fica pendente. A empresa perde tempo, não
   resultado.

O que isto NÃO faz: aumentar a cota. Acima do que o projeto comporta, o caminho é
pedir ampliação ao Google (auditoria de conformidade da YouTube API Services).
"""

import logging
import math
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.uso_cota_youtube import ID_AJUSTE, UsoCotaYoutube

logger = logging.getLogger(__name__)

# A API zera a cota à meia-noite do Pacífico, com horário de verão. Não dá para usar
# um deslocamento fixo como em `workers/coleta.FUSO_BRASILIA`: o Pacífico muda de
# UTC-7 para UTC-8 no meio do ano. Precisa do pacote `tzdata` fora do Linux.
FUSO_COTA = ZoneInfo("America/Los_Angeles")

# Linhas mais velhas que isto saem na própria escrita (regra 7 do CLAUDE.md).
DIAS_DE_HISTORICO = 35

UNIDADES_POR_PAGINA = 1
COMENTARIOS_POR_PAGINA = 100
VIDEOS_POR_CHAMADA = 50

MOTIVO_COTA = "Aguardando a cota diária do YouTube renovar"


def dia_da_cota(agora: datetime) -> date:
    """O dia que a API considera: o do Pacífico, e não o de Brasília nem o UTC."""
    return agora.astimezone(FUSO_COTA).date()


def proxima_renovacao(agora: datetime) -> datetime:
    """A próxima meia-noite do Pacífico, em UTC. É quando a coleta adiada volta."""
    local = agora.astimezone(FUSO_COTA)
    amanha = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=FUSO_COTA)
    return amanha.astimezone(UTC)


def estimar_custo(total_videos: int, limite_comentarios: int) -> int:
    """Unidades que uma coleta custa, SEM filtro que descarte (o caso comum).

    É uma estimativa da entrada: uma página por 100 comentários pedidos, mais uma
    página final incompleta por vídeo e as chamadas de `videos.list`. Com termo de
    pesquisa ou data o custo real pode passar disto; o teto de leitura e o orçamento
    medido durante a coleta (`ClienteYouTube.medir`) cobrem esse caso.

    Limitada à fatia da empresa: uma estimativa maior que o que ela pode gastar num
    dia adiaria a coleta para sempre.
    """
    paginas = math.ceil(max(limite_comentarios, 1) / COMENTARIOS_POR_PAGINA)
    chamadas_de_video = math.ceil(max(total_videos, 1) / VIDEOS_POR_CHAMADA)
    custo = (paginas + max(total_videos, 1) + chamadas_de_video) * UNIDADES_POR_PAGINA
    return min(custo, settings.youtube_cota_fatia_por_empresa)


async def _gastos_do_dia(db: AsyncSession, dia: date) -> dict[int, int]:
    linhas = await db.execute(
        select(UsoCotaYoutube.id_empresa, UsoCotaYoutube.unidades).where(UsoCotaYoutube.dia == dia)
    )
    return {id_empresa: unidades for id_empresa, unidades in linhas}


async def usado_hoje(db: AsyncSession, agora: datetime | None = None) -> int:
    """Total do dia da cota, de todas as empresas (mais o ajuste)."""
    agora = agora or datetime.now(UTC)
    return sum((await _gastos_do_dia(db, dia_da_cota(agora))).values())


async def orcamento_da_empresa(db: AsyncSession, id_empresa: int, agora: datetime) -> int:
    """Quantas unidades a empresa pode gastar AGORA. Zero manda a coleta esperar.

    Três limites, vale o menor:

    - o que resta do dia, descontada a reserva;
    - o maior entre (a) o que falta da fatia da empresa e (b) a folga compartilhada, isto é,
      o que ainda cabe até a fração `youtube_cota_folga_compartilhada` do dia.

    Com o dia vazio, qualquer empresa pode usar até 70%. Quando o dia passa disso, a
    empresa que já gastou mais que a fatia espera; a que gastou menos ainda tem o resto
    da fatia. Assim ninguém consome o dia inteiro, e ninguém fica sem a própria parte.
    """
    gastos = await _gastos_do_dia(db, dia_da_cota(agora))
    total = sum(gastos.values())
    da_empresa = gastos.get(id_empresa, 0)

    livre_no_dia = settings.youtube_cota_diaria - settings.youtube_cota_reserva - total
    resto_da_fatia = settings.youtube_cota_fatia_por_empresa - da_empresa
    folga = int(settings.youtube_cota_diaria * settings.youtube_cota_folga_compartilhada) - total

    return max(0, min(livre_no_dia, max(resto_da_fatia, folga)))


async def registrar_uso(
    db: AsyncSession, id_empresa: int, unidades: int, agora: datetime | None = None
) -> None:
    """Soma `unidades` ao dia da empresa e faz commit. Atômico: duas coletas somam as duas.

    `INSERT ... ON CONFLICT DO UPDATE` (e não ler e gravar) porque os workers podem ser
    mais de um processo. As linhas fora do histórico saem na mesma transação.
    """
    if unidades <= 0:
        return
    agora = agora or datetime.now(UTC)
    dia = dia_da_cota(agora)

    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    await db.execute(
        insert(UsoCotaYoutube)
        .values(dia=dia, id_empresa=id_empresa, unidades=unidades)
        .on_conflict_do_update(
            index_elements=["dia", "id_empresa"],
            set_={"unidades": UsoCotaYoutube.unidades + unidades},
        )
    )
    await db.execute(
        delete(UsoCotaYoutube).where(UsoCotaYoutube.dia < dia - timedelta(days=DIAS_DE_HISTORICO))
    )
    await db.commit()


async def marcar_esgotada(db: AsyncSession, agora: datetime | None = None) -> None:
    """A API disse que a cota acabou: iguala o contador do dia ao limite.

    Acontece quando alguém gastou unidades por fora (a mesma chave num script, num teste
    manual) ou a nossa contagem ficou atrasada. Sem isto, cada coleta seguinte bateria
    na API para descobrir a mesma coisa. O excedente vai para o ajuste, e não para
    uma empresa, porque não foi nenhuma delas.
    """
    agora = agora or datetime.now(UTC)
    total = await usado_hoje(db, agora)
    falta = settings.youtube_cota_diaria - total
    if falta > 0:
        await registrar_uso(db, ID_AJUSTE, falta, agora)
        logger.warning(
            "cota do dia marcada como esgotada pela API ajuste=%s usado_antes=%s", falta, total
        )
