"""Worker de coleta: consome jobs tipo 'coleta' e popula VIDEOS e COMENTARIOS.

Roda FORA do FastAPI (`python -m app.workers.runner`). A regra do CLAUDE.md é que
coleta nunca acontece dentro de uma requisição HTTP — o endpoint só enfileira.

Reprodutibilidade: os parâmetros saem de `jobs.payload`, congelados no disparo.
O worker NUNCA relê MODELOS_ANALISE; se o usuário editar o modelo no meio da
coleta, a execução continua sendo a que foi pedida.

A coleta NÃO encerra a execução: ao concluir, ela publica o job da etapa seguinte na
mesma transação e a execução segue em `processando` (`workers/pipeline.py`). Coletar
comentário sem classificar não é resultado nenhum para a PME — a execução só está
pronta quando a análise está.
"""

import asyncio
import logging
import random
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone

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
    LoteComentarios,
    VideoColetado,
)

logger = logging.getLogger(__name__)

TIPO_JOB = "coleta"

# Chaves que o worker sabe interpretar. O schema do UC02 usa extra="allow", então
# o filtro pode chegar com qualquer coisa — o combinado é avisar, não quebrar.
CHAVES_CONHECIDAS = frozenset({"videos", "canais", "publicado_apos", "limite_comentarios"})

# "Comentários a partir de" é uma DATA escolhida por uma PME brasileira: começa à
# meia-noite de Brasília, não à de Greenwich. Deslocamento fixo porque o Brasil não
# tem horário de verão desde 2019, e porque `zoneinfo` no Windows depende de um
# pacote a mais (tzdata) só para isto.
FUSO_BRASILIA = timezone(timedelta(hours=-3))

# Onde o worker registra, no próprio job, o recorte que de fato aplicou. O resto do
# payload é o pedido congelado no disparo e não muda; esta chave é o resultado.
CHAVE_RECORTE = "recorte_aplicado"


@dataclass(frozen=True)
class Recorte:
    """Os filtros da coleta já interpretados — o que o worker vai de fato aplicar."""

    termo: str
    publicado_apos: date | None
    limite_informado: int | None
    limite_aplicado: int

    @property
    def inicio(self) -> datetime | None:
        if self.publicado_apos is None:
            return None
        return datetime.combine(self.publicado_apos, time.min, tzinfo=FUSO_BRASILIA)


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


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento: "Tênis" e "tenis" são o mesmo termo para a PME."""
    decomposto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def contem_termo(termo: str):
    """O filtro do termo de pesquisa: o comentário CONTÉM o termo, como a tela promete.

    Local, sobre o texto original, e não o `searchTerms` da API: o critério de busca
    do YouTube não é documentado, e o que a tela afirma tem de ser verificável.
    """
    alvo = normalizar(termo)
    return lambda texto: alvo in normalizar(texto)


def _recorte(payload: dict, id_execucao: int) -> Recorte:
    """Interpreta termo, data e limite do payload congelado.

    O cadastro já recusa valor inválido (`schemas/modelo_analise.py`). Aqui o que
    chega torto é modelo salvo antes da validação: o filtro é ignorado com aviso, no
    mesmo combinado das chaves desconhecidas — não derruba a coleta.
    """
    filtros = payload.get("filtros") or {}
    teto = settings.worker_max_comentarios_por_execucao

    publicado_apos: date | None = None
    bruto = filtros.get("publicado_apos")
    if bruto:
        try:
            publicado_apos = date.fromisoformat(str(bruto))
        except ValueError:
            logger.warning(
                "publicado_apos invalido, ignorado id_execucao=%s valor=%r", id_execucao, bruto
            )

    limite_informado: int | None = None
    bruto = filtros.get("limite_comentarios")
    if bruto is not None:
        if isinstance(bruto, int) and not isinstance(bruto, bool) and bruto >= 1:
            limite_informado = bruto
        else:
            logger.warning(
                "limite_comentarios invalido, ignorado id_execucao=%s valor=%r",
                id_execucao,
                bruto,
            )

    return Recorte(
        termo=str(payload.get("termo_pesquisa") or "").strip(),
        publicado_apos=publicado_apos,
        limite_informado=limite_informado,
        # O menor entre o pedido e o teto do worker (escopo do projeto: 5.000).
        limite_aplicado=min(limite_informado, teto) if limite_informado else teto,
    )


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
    db: AsyncSession,
    job: Job,
    cliente: ClienteYouTube,
    coletado: VideoColetado,
    recorte: Recorte,
    limite: int,
    max_lidos: int,
) -> LoteComentarios:
    """Persiste o vídeo e seus comentários. Devolve o lote (gravados e contagens)."""
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
        lote = await _com_retry(
            db,
            job,
            lambda: cliente.listar_comentarios(
                coletado.youtube_video_id,
                limite,
                publicado_apos=recorte.inicio,
                aceitar_texto=contem_termo(recorte.termo) if recorte.termo else None,
                max_lidos=max_lidos,
            ),
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
        return LoteComentarios()

    for comentario in lote.comentarios:
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

    return lote


async def processar(db: AsyncSession, job: Job, cliente: ClienteYouTube) -> int:
    """Executa um job de coleta já reivindicado. Devolve o total de comentários."""
    payload = job.payload or {}
    ids = _ids_de_video(payload, job.id_execucao)
    recorte = _recorte(payload, job.id_execucao)

    logger.info(
        "coleta iniciada id_execucao=%s videos=%s termo=%r publicado_apos=%s "
        "limite_informado=%s limite_aplicado=%s",
        job.id_execucao,
        len(ids),
        recorte.termo,
        recorte.publicado_apos,
        recorte.limite_informado,
        recorte.limite_aplicado,
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

    # O limite e o teto de leitura são da EXECUÇÃO, repartidos entre os vídeos na
    # ordem em que a API os devolveu.
    restante = recorte.limite_aplicado
    leitura_restante = settings.worker_max_comentarios_lidos_por_execucao
    total = lidos = por_data = por_termo = 0

    for coletado in videos:
        if restante <= 0 or leitura_restante <= 0:
            logger.warning(
                "limite atingido, videos restantes ignorados id_execucao=%s "
                "limite_aplicado=%s lidos=%s teto_leitura=%s",
                job.id_execucao,
                recorte.limite_aplicado,
                lidos,
                settings.worker_max_comentarios_lidos_por_execucao,
            )
            break

        lote = await _coletar_video(db, job, cliente, coletado, recorte, restante, leitura_restante)
        gravados = len(lote.comentarios)
        restante -= gravados
        leitura_restante -= lote.lidos
        total += gravados
        lidos += lote.lidos
        por_data += lote.descartados_por_data
        por_termo += lote.descartados_por_termo

    # O recorte que de fato valeu, ao lado do pedido congelado: é o que a tela de
    # resultados mostra para deixar claro de onde saem os números. Reatribuição (e não
    # mutação) para o SQLAlchemy perceber a mudança na coluna JSON.
    job.payload = {
        **payload,
        CHAVE_RECORTE: {
            "coletado_em": datetime.now(UTC).isoformat(),
            "termo_pesquisa": recorte.termo or None,
            "publicado_apos": recorte.publicado_apos and recorte.publicado_apos.isoformat(),
            "limite_informado": recorte.limite_informado,
            "limite_aplicado": recorte.limite_aplicado,
            "comentarios_lidos": lidos,
            "comentarios_coletados": total,
            "descartados_por_data": por_data,
            "descartados_por_termo": por_termo,
        },
    }

    # Um commit só no fim: execução sem vídeo nenhum ou com tudo gravado, nunca
    # um meio-termo que o usuário veria como 'concluida' pela metade.
    await db.commit()

    logger.info(
        "coleta finalizada id_execucao=%s videos=%s comentarios=%s lidos=%s "
        "descartados_por_data=%s descartados_por_termo=%s",
        job.id_execucao,
        len(videos),
        total,
        lidos,
        por_data,
        por_termo,
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
