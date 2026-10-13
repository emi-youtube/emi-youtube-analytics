"""Expurgo: o que vem do YouTube não fica mais de 30 dias (ADR-015, `services/guarda.py`).

Roda dentro do laço do runner, a cada `worker_expurgo_intervalo_segundos`, como o
reaper: é uma consulta curta, e um serviço agendado à parte custaria um contêiner a
mais no crédito do Azure (CLAUDE.md Seção 10). Quatro passos, cada um com seu commit,
na ordem em que importam para a conformidade:

1. **Texto dos comentários** das execuções que passaram do prazo: `texto`,
   `autor_hash` e `youtube_comment_id` viram nulo, e a `justificativa` da análise
   também, porque pode citar o comentário. A linha do comentário, a análise e o tema
   ficam: são o resultado que a empresa continua vendo.
2. **Vídeos vencidos**: título, canal e data que chegaram ao prazo sem ser atualizados
   são apagados.
3. **Resultados com mais de 36 meses**: a execução sai inteira.
4. **Atualização dos vídeos**: a partir do 25º dia, título, canal e data são buscados
   de novo (`videos.list`, 1 unidade a cada 50 vídeos, cobrada da empresa dona). O
   vídeo que não volta (removido, privado) tem esses campos apagados.

O passo 4 é o único que fala com a rede, e por isso vem por último: uma falha dele não
impede os outros. Visualizações e curtidas NÃO são atualizadas: são o retrato da
coleta, e a comparação entre coletas da campanha depende dele.

**Por que não apagar a linha do comentário.** `analises_sentimento` e
`comentario_tema` penduram nela, e são o resultado. O que sai é o que veio da API.

**O que ele não toca:** `exemplos_treinamento`. O corpus de pesquisa tem sua própria
cópia do texto e um prazo próprio, o fim do TCC (Termos de Uso 1.2, seção 6).
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.video import Video
from app.services import cota
from app.services.guarda import prazo_dos_comentarios, prazo_dos_resultados
from app.workers.youtube import (
    MAX_IDS_POR_CHAMADA,
    ClienteYouTube,
    CotaEsgotada,
    ErroYouTube,
    VideoColetado,
)

logger = logging.getLogger(__name__)

STATUS_ATIVOS = ("pendente", "processando")


@dataclass
class ResumoExpurgo:
    """O que uma passada fez. Vai para o log e para os testes."""

    execucoes_com_texto_apagado: list[int] = field(default_factory=list)
    videos_atualizados: int = 0
    videos_apagados: int = 0
    execucoes_apagadas: list[int] = field(default_factory=list)

    @property
    def fez_algo(self) -> bool:
        return bool(
            self.execucoes_com_texto_apagado
            or self.videos_atualizados
            or self.videos_apagados
            or self.execucoes_apagadas
        )


# --------------------------------------------------------------------------- 1. comentários


async def apagar_comentarios_vencidos(db: AsyncSession, agora: datetime) -> list[int]:
    """Apaga o texto dos comentários das execuções que passaram do prazo. Faz commit.

    Vale para qualquer status: uma execução parada em `erro` também guarda texto, e o
    prazo é do dado, não do processo. Uma execução por commit, para que uma falha no
    meio não desfaça as anteriores.
    """
    limite = agora - prazo_dos_comentarios()
    vencidas = list(
        (
            await db.scalars(
                select(Execucao.id_execucao)
                .where(
                    Execucao.iniciado_em.is_not(None),
                    Execucao.iniciado_em <= limite,
                    Execucao.comentarios_apagados_em.is_(None),
                )
                .order_by(Execucao.id_execucao)
            )
        ).all()
    )

    for id_execucao in vencidas:
        videos = select(Video.id_video).where(Video.id_execucao == id_execucao)
        comentarios = select(Comentario.id_comentario).where(Comentario.id_video.in_(videos))

        await db.execute(
            update(AnaliseSentimento)
            .where(AnaliseSentimento.id_comentario.in_(comentarios))
            .values(justificativa=None)
            .execution_options(synchronize_session=False)
        )
        apagados = await db.execute(
            update(Comentario)
            .where(Comentario.id_video.in_(videos))
            .values(texto=None, autor_hash=None, youtube_comment_id=None)
            .execution_options(synchronize_session=False)
        )
        await db.execute(
            update(Execucao)
            .where(Execucao.id_execucao == id_execucao)
            .values(comentarios_apagados_em=agora)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        logger.info(
            "expurgo: texto dos comentarios apagado id_execucao=%s comentarios=%s",
            id_execucao,
            apagados.rowcount,
        )

    return vencidas


# --------------------------------------------------------------------------- 2. vídeos vencidos


def _apagar_metadados():
    return {"titulo": "", "canal": "", "publicado_em": None, "metadados_em": None}


async def apagar_videos_vencidos(db: AsyncSession, agora: datetime) -> int:
    """Apaga título, canal e data dos vídeos que chegaram ao prazo sem atualizar. Commit."""
    limite = agora - prazo_dos_comentarios()
    resultado = await db.execute(
        update(Video)
        .where(Video.metadados_em.is_not(None), Video.metadados_em <= limite)
        .values(**_apagar_metadados())
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if resultado.rowcount:
        logger.warning(
            "expurgo: %s video(s) chegaram ao prazo sem atualizar; titulo e canal apagados",
            resultado.rowcount,
        )
    return resultado.rowcount


# --------------------------------------------------------------------------- 3. resultados


async def apagar_resultados_vencidos(db: AsyncSession, agora: datetime) -> list[int]:
    """Apaga as execuções com mais de 36 meses, inteiras. Faz commit.

    A ordem é a de `services/conta._apagar_empresa`: `jobs`, `jobs_dlq` e `temas` não têm
    cascata; `videos` leva `comentarios`, que leva `analises_sentimento` e
    `comentario_tema`. Execução em andamento fica para a próxima passada.
    """
    limite = agora - prazo_dos_resultados()
    vencidas = list(
        (
            await db.scalars(
                select(Execucao.id_execucao).where(
                    Execucao.iniciado_em.is_not(None),
                    Execucao.iniciado_em <= limite,
                    Execucao.status.not_in(STATUS_ATIVOS),
                )
            )
        ).all()
    )
    if not vencidas:
        return []

    for tabela, coluna in (
        (JobDlq, JobDlq.id_execucao),
        (Job, Job.id_execucao),
        (Tema, Tema.id_execucao),
        (Video, Video.id_execucao),
        (Execucao, Execucao.id_execucao),
    ):
        await db.execute(
            delete(tabela).where(coluna.in_(vencidas)).execution_options(synchronize_session=False)
        )
    await db.commit()
    logger.info("expurgo: execucoes com mais de 36 meses apagadas ids=%s", vencidas)
    return vencidas


# --------------------------------------------------------------------------- 4. atualização


async def _videos_a_atualizar(
    db: AsyncSession, agora: datetime
) -> dict[int, list[tuple[int, str]]]:
    """`{id_empresa: [(id_video, youtube_video_id)]}`, os mais antigos primeiro."""
    a_partir = agora - timedelta(days=settings.youtube_atualizar_metadados_apos_dias)
    linhas = await db.execute(
        select(ModeloAnalise.id_empresa, Video.id_video, Video.youtube_video_id)
        .join(Execucao, Execucao.id_execucao == Video.id_execucao)
        .join(ModeloAnalise, ModeloAnalise.id_modelo == Execucao.id_modelo)
        .where(Video.metadados_em.is_not(None), Video.metadados_em <= a_partir)
        .order_by(Video.metadados_em, Video.id_video)
    )
    por_empresa: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for id_empresa, id_video, youtube_video_id in linhas:
        por_empresa[id_empresa].append((id_video, youtube_video_id))
    return por_empresa


async def _buscar(
    db: AsyncSession, cliente: ClienteYouTube, id_empresa: int, ids: list[str], agora: datetime
) -> tuple[set[str], dict[str, VideoColetado], bool]:
    """Busca os vídeos na API dentro do orçamento da empresa e registra o gasto.

    Devolve (ids consultados, encontrados, cota da API esgotada). Só conta como
    consultado o lote que voltou: um lote interrompido fica para a próxima passada.
    """
    orcamento = await cota.orcamento_da_empresa(db, id_empresa, agora)
    consultados: set[str] = set()
    encontrados: dict[str, VideoColetado] = {}
    if orcamento <= 0:
        return consultados, encontrados, False

    esgotada_na_api = False
    with cliente.medir(orcamento) as medida:
        try:
            for inicio in range(0, len(ids), MAX_IDS_POR_CHAMADA):
                lote = ids[inicio : inicio + MAX_IDS_POR_CHAMADA]
                for video in await cliente.listar_videos(lote):
                    encontrados[video.youtube_video_id] = video
                consultados.update(lote)
        except CotaEsgotada as erro:
            esgotada_na_api = erro.da_api
            logger.warning(
                "expurgo: atualizacao parou por cota id_empresa=%s: %s", id_empresa, erro
            )
        except ErroYouTube as erro:
            # Transitório ou não, tenta de novo na próxima passada: há dias de folga.
            logger.warning("expurgo: atualizacao falhou id_empresa=%s: %s", id_empresa, erro)

    if esgotada_na_api:
        await cota.marcar_esgotada(db, agora)
    await cota.registrar_uso(db, id_empresa, medida.unidades, agora)
    return consultados, encontrados, esgotada_na_api


async def atualizar_videos(
    db: AsyncSession, cliente: ClienteYouTube, agora: datetime
) -> tuple[int, int]:
    """Atualiza título, canal e data dos vídeos perto do prazo. Devolve (atualizados, apagados).

    Agrupado por empresa porque a cota é da empresa (ADR-015): a atualização dos vídeos
    dela sai do orçamento dela, como a coleta. O mesmo vídeo em duas execuções da mesma
    empresa custa uma consulta só.
    """
    atualizados = apagados = 0
    for id_empresa, videos in (await _videos_a_atualizar(db, agora)).items():
        ids = list(dict.fromkeys(youtube_video_id for _, youtube_video_id in videos))
        consultados, encontrados, parar = await _buscar(db, cliente, id_empresa, ids, agora)

        for id_video, youtube_video_id in videos:
            if youtube_video_id not in consultados:
                continue
            video = encontrados.get(youtube_video_id)
            if video is None:
                valores = _apagar_metadados()
                apagados += 1
            else:
                valores = {
                    "titulo": video.titulo,
                    "canal": video.canal,
                    "publicado_em": video.publicado_em,
                    "metadados_em": agora,
                }
                atualizados += 1
            await db.execute(
                update(Video)
                .where(Video.id_video == id_video)
                .values(**valores)
                .execution_options(synchronize_session=False)
            )
        await db.commit()

        if parar:
            # A API disse que o dia acabou: as outras empresas também não conseguiriam.
            break

    if atualizados or apagados:
        logger.info("expurgo: videos atualizados=%s apagados=%s", atualizados, apagados)
    return atualizados, apagados


# --------------------------------------------------------------------------- passada


async def executar(
    db: AsyncSession, cliente: ClienteYouTube, agora: datetime | None = None
) -> ResumoExpurgo:
    """Uma passada completa, na ordem do docstring do módulo."""
    agora = agora or datetime.now(UTC)
    resumo = ResumoExpurgo()
    resumo.execucoes_com_texto_apagado = await apagar_comentarios_vencidos(db, agora)
    resumo.videos_apagados += await apagar_videos_vencidos(db, agora)
    resumo.execucoes_apagadas = await apagar_resultados_vencidos(db, agora)
    atualizados, apagados = await atualizar_videos(db, cliente, agora)
    resumo.videos_atualizados = atualizados
    resumo.videos_apagados += apagados
    return resumo
