"""Worker de coleta: consome jobs tipo 'coleta' e popula VIDEOS e COMENTARIOS.

Roda FORA do FastAPI (`python -m app.workers.runner`). A regra do CLAUDE.md é que
coleta nunca acontece dentro de uma requisição HTTP — o endpoint só enfileira.

Reprodutibilidade: os parâmetros saem de `jobs.payload`, congelados no disparo.
O worker NUNCA relê MODELOS_ANALISE; se o usuário editar o modelo no meio da
coleta, a execução continua sendo a que foi pedida.
"""

import asyncio
import logging
import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.comentario import Comentario
from app.models.job import Job
from app.models.video import Video
from app.workers import fila
from app.workers.youtube import (
    ClienteYouTube,
    ComentariosDesabilitados,
    ErroPermanente,
    ErroTransitorio,
    VideoColetado,
)

logger = logging.getLogger(__name__)

TIPO_JOB = "coleta"

# Chaves que o worker sabe interpretar. O schema do UC02 usa extra="allow", então
# o filtro pode chegar com qualquer coisa — o combinado é avisar, não quebrar.
CHAVES_CONHECIDAS = frozenset({"videos", "canais"})

# Espera entre tentativas: 2, 4, 8, 16s. O jitter evita que vários workers que
# tomaram 429 ao mesmo tempo voltem juntos e tomem 429 de novo.
BACKOFF_BASE = 2
JITTER_MAXIMO = 1.0


class FalhaColeta(Exception):
    """Falha que encerra o job: vai para a DLQ e marca a execução como 'erro'."""


async def _esperar(segundos: float) -> None:
    """Isolado para o teste pular a espera sem mexer no `asyncio` global."""
    await asyncio.sleep(segundos)


def _backoff(tentativa: int) -> float:
    return BACKOFF_BASE**tentativa + random.uniform(0, JITTER_MAXIMO)


def _ids_de_video(payload: dict, id_execucao: int) -> list[str]:
    """Extrai os IDs curados do filtro congelado, avisando o que não foi entendido."""
    filtros = payload.get("filtros") or {}

    desconhecidas = set(filtros) - CHAVES_CONHECIDAS
    if desconhecidas:
        # Combinado no UC02: chave que o worker não entende não derruba a coleta,
        # mas não pode passar silenciosa.
        logger.warning(
            "filtro com chave(s) desconhecida(s), ignorada(s) id_execucao=%s chaves=%s",
            id_execucao,
            sorted(desconhecidas),
        )

    if filtros.get("canais"):
        # Expandir canal em vídeos exigiria search.list (100 unidades, proibido pelo
        # CLAUDE.md). channels.list + playlistItems.list fariam isso por 1 unidade,
        # mas isso é escopo de outro card.
        logger.warning(
            "filtro 'canais' ainda não é expandido pelo worker id_execucao=%s", id_execucao
        )

    ids = [str(v).strip() for v in filtros.get("videos", []) if str(v).strip()]
    if not ids:
        raise FalhaColeta(
            "Nenhum ID de vídeo no filtro do modelo: a coleta não tem o que buscar. "
            "Informe 'videos' nos filtros (os vídeos são curados manualmente)."
        )
    return ids


async def _com_retry(db: AsyncSession, job: Job, operacao, descricao: str):
    """Repete `operacao` em erro transitório, com backoff exponencial + jitter.

    O orçamento de tentativas é do JOB, não de cada chamada: um job que só toma
    429 não fica repetindo para sempre a cada vídeo da lista.
    """
    while True:
        try:
            return await operacao()
        except ErroTransitorio as erro:
            tentativas = await fila.registrar_tentativa(db, job)
            if tentativas > settings.worker_max_retries:
                raise FalhaColeta(
                    f"{descricao}: esgotadas as {settings.worker_max_retries} tentativas ({erro})"
                ) from erro

            espera = _backoff(tentativas)
            logger.warning(
                "erro transitorio, nova tentativa id_execucao=%s tentativa=%s espera=%.1fs %s: %s",
                job.id_execucao,
                tentativas,
                espera,
                descricao,
                erro,
            )
            await _esperar(espera)
        except ErroPermanente as erro:
            # Chave inválida, cota estourada, vídeo inexistente: repetir só gasta tempo.
            raise FalhaColeta(f"{descricao}: {erro}") from erro


async def _coletar_video(
    db: AsyncSession, job: Job, cliente: ClienteYouTube, coletado: VideoColetado, limite: int
) -> int:
    """Persiste o vídeo e seus comentários. Devolve quantos comentários gravou."""
    video = Video(
        id_execucao=job.id_execucao,
        youtube_video_id=coletado.youtube_video_id,
        titulo=coletado.titulo,
        canal=coletado.canal,
        publicado_em=coletado.publicado_em,
        visualizacoes=coletado.visualizacoes,
        curtidas=coletado.curtidas,
    )
    db.add(video)
    # flush para o banco atribuir o id_video que os comentários referenciam.
    await db.flush()

    try:
        comentarios = await _com_retry(
            db,
            job,
            lambda: cliente.listar_comentarios(coletado.youtube_video_id, limite),
            f"comentarios do video {coletado.youtube_video_id}",
        )
    except ComentariosDesabilitados:
        # O vídeo fica registrado com zero comentários: faz parte do resultado da
        # campanha e não pode derrubar a execução inteira.
        logger.warning(
            "video com comentarios desabilitados, registrado com zero id_execucao=%s video=%s",
            job.id_execucao,
            coletado.youtube_video_id,
        )
        return 0

    for comentario in comentarios:
        db.add(
            Comentario(
                id_video=video.id_video,
                youtube_comment_id=comentario.youtube_comment_id,
                # Já chega hasheado do cliente — o autor original nunca entra aqui.
                autor_hash=comentario.autor_hash,
                texto=comentario.texto,
                publicado_em=comentario.publicado_em,
            )
        )

    return len(comentarios)


async def processar(db: AsyncSession, job: Job, cliente: ClienteYouTube) -> int:
    """Executa um job de coleta já reivindicado. Devolve o total de comentários."""
    payload = job.payload or {}
    ids = _ids_de_video(payload, job.id_execucao)

    logger.info(
        "coleta iniciada id_execucao=%s videos=%s termo=%r",
        job.id_execucao,
        len(ids),
        payload.get("termo_pesquisa"),
    )

    videos = await _com_retry(db, job, lambda: cliente.listar_videos(ids), "metadados dos videos")

    ausentes = set(ids) - {v.youtube_video_id for v in videos}
    if ausentes:
        # Vídeo removido ou privado depois da curadoria: some da resposta da API.
        logger.warning(
            "video(s) do filtro nao retornado(s) pela API id_execucao=%s videos=%s",
            job.id_execucao,
            sorted(ausentes),
        )

    restante = settings.worker_max_comentarios_por_execucao
    total = 0

    for coletado in videos:
        if restante <= 0:
            logger.warning(
                "teto de %s comentarios atingido, videos restantes ignorados id_execucao=%s",
                settings.worker_max_comentarios_por_execucao,
                job.id_execucao,
            )
            break

        gravados = await _coletar_video(db, job, cliente, coletado, restante)
        restante -= gravados
        total += gravados

    # Um commit só no fim: execução sem vídeo nenhum ou com tudo gravado, nunca
    # um meio-termo que o usuário veria como 'concluida' pela metade.
    await db.commit()

    logger.info(
        "coleta finalizada id_execucao=%s videos=%s comentarios=%s",
        job.id_execucao,
        len(videos),
        total,
    )
    return total


async def _descartar_parcial(db: AsyncSession, job: Job) -> None:
    """Desfaz o que a coleta tinha gravado e recarrega o job.

    O rollback expira os objetos da sessão; sem o refresh, ler `job.tipo` para
    montar a linha da DLQ dispararia um carregamento preguiçoso fora do contexto
    assíncrono do SQLAlchemy.
    """
    await db.rollback()
    await db.refresh(job)


async def executar_proximo(db: AsyncSession, cliente: ClienteYouTube) -> bool:
    """Reivindica e processa um job. `False` quando não havia nada na fila."""
    job = await fila.reivindicar(db, TIPO_JOB)
    if job is None:
        return False

    try:
        await processar(db, job, cliente)
    except FalhaColeta as erro:
        await _descartar_parcial(db, job)
        await fila.enviar_para_dlq(db, job, str(erro))
        return True
    except Exception as erro:
        # Rede de segurança: nenhum job pode ficar preso em 'processando'.
        await _descartar_parcial(db, job)
        logger.exception("falha inesperada na coleta id_execucao=%s", job.id_execucao)
        await fila.enviar_para_dlq(db, job, f"erro inesperado: {erro!r}")
        return True

    await fila.concluir(db, job)
    return True
