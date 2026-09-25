"""Worker de inferência: consome jobs tipo 'inferencia' e popula ANALISES_SENTIMENTO.

Roda FORA do FastAPI (`python -m app.workers.runner`), como a coleta. O job chega
publicado pela etapa anterior, na mesma transação em que ela se concluiu
(`workers/pipeline.py`): é este worker que encerra a execução.

**Transporte, não método.** Este arquivo lê comentário, aplica `preparar_texto`, chama
`classificador.classificar` e grava a linha. Qual classificador está em pé é decidido
no `runner`; hoje é o léxico, amanhã o BERTimbau, e nada aqui muda — é o que torna a
troca verificável (`app/inferencia/base.py`).

**Idempotente.** Reprocessar uma execução não duplica nem quebra: o worker só busca
comentários que ainda não têm análise, e `ANALISES_SENTIMENTO` tem `UNIQUE
(id_comentario)` como rede por baixo. Isso é o que permite commitar por lote — uma
queda no meio deixa progresso aproveitável, ao contrário da coleta, que descarta o
parcial porque não tem como retomar de onde parou sem gastar cota de novo.

**Erro local não é transitório.** A coleta repete com backoff porque fala com uma API
que devolve 429 e 503. Aqui não há rede: se o classificador falhou num texto, vai
falhar de novo no mesmo texto. Repetir só atrasa a ida para a DLQ, então não há
retentativa nenhuma.
"""

import logging
from collections.abc import Sequence

from preprocessamento import preparar_texto
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inferencia.base import SENTIMENTOS_VALIDOS, Classificador
from app.inferencia.versao import garantir_versao
from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.job import Job
from app.models.video import Video
from app.workers import fila

logger = logging.getLogger(__name__)

TIPO_JOB = "inferencia"

# Comentários lidos e gravados por transação. Dentro do escopo do projeto (500 a
# 5.000 por execução) caberia tudo de uma vez; o lote existe pela outra razão: ele
# transforma a idempotência em retomada. Uma queda no comentário 3.000 deixa 2.500
# análises gravadas, e o reprocessamento começa de onde parou.
TAMANHO_DO_LOTE = 500


class FalhaInferencia(Exception):
    """Falha que encerra o job: vai para a DLQ e marca a execução como 'erro'."""


def _sem_analise(id_execucao: int):
    """Comentários da execução que ainda não têm análise, em ordem estável.

    `NOT EXISTS` (e não `NOT IN`) porque a subconsulta é correlacionada e para no
    primeiro acerto. A ordem por `id_comentario` é o que faz o lote seguinte começar
    onde o anterior parou sem OFFSET — as linhas já gravadas saem do resultado
    sozinhas, porque passam a ter análise.
    """
    ja_analisado = exists().where(AnaliseSentimento.id_comentario == Comentario.id_comentario)
    return (
        select(Comentario)
        .join(Video, Video.id_video == Comentario.id_video)
        .where(Video.id_execucao == id_execucao, ~ja_analisado)
        .order_by(Comentario.id_comentario)
        .limit(TAMANHO_DO_LOTE)
    )


async def _proximo_lote(db: AsyncSession, id_execucao: int) -> Sequence[Comentario]:
    resultado = await db.scalars(_sem_analise(id_execucao))
    return resultado.all()


def _analisar(
    comentario: Comentario, classificador: Classificador, id_versao: int
) -> AnaliseSentimento:
    """Classifica um comentário e monta a linha, sem tocar no banco.

    `preparar_texto` é aplicado AQUI, e não dentro da implementação: é o mesmo
    pré-processamento do treino (CLAUDE.md Seção 3), e aplicá-lo num lugar só é o que
    garante que léxico e BERTimbau leiam exatamente o mesmo texto. O banco guarda o
    original; o texto preparado é derivado e não é persistido.
    """
    texto_modelo = preparar_texto(comentario.texto)
    classificacao = classificador.classificar(texto_modelo)

    if classificacao.sentimento not in SENTIMENTOS_VALIDOS:
        # Conferido antes de gravar: um rótulo fora do CHECK viraria IntegrityError no
        # commit do lote, e a mensagem do banco não diria qual implementação errou.
        # É exatamente o bug que a regra 5 do CLAUDE.md descreve (ordem de rótulos
        # hardcodada), aparecendo alto em vez de em silêncio.
        raise FalhaInferencia(
            f"classificador {classificador.descritor.nome_modelo} devolveu sentimento "
            f"{classificacao.sentimento!r}, fora de {sorted(SENTIMENTOS_VALIDOS)} "
            f"(id_comentario={comentario.id_comentario})"
        )

    return AnaliseSentimento(
        id_comentario=comentario.id_comentario,
        id_versao_modelo=id_versao,
        sentimento=classificacao.sentimento,
        # `tema` fica nulo: quem preenche é o worker de tópicos, que roda por execução
        # e grava também em TEMAS e COMENTARIO_TEMA. Inferência não inventa tema.
        tema=None,
        justificativa=classificacao.justificativa,
    )


async def processar(db: AsyncSession, job: Job, classificador: Classificador) -> int:
    """Classifica os comentários pendentes da execução. Devolve quantos gravou.

    Zero é resultado válido, não erro: uma execução cujos vídeos todos tinham
    comentário desabilitado não tem o que classificar, e reprocessar uma execução já
    analisada também devolve zero — é a idempotência funcionando.
    """
    versao = await garantir_versao(db, classificador.descritor)

    logger.info(
        "inferencia iniciada id_execucao=%s classificador=%s versao=%s id_versao=%s",
        job.id_execucao,
        versao.nome_modelo,
        versao.versao,
        versao.id_versao,
    )

    total = 0
    while True:
        comentarios = await _proximo_lote(db, job.id_execucao)
        if not comentarios:
            break

        for comentario in comentarios:
            db.add(_analisar(comentario, classificador, versao.id_versao))

        # Commit por lote: o que já foi classificado fica gravado. Seguro porque o
        # próximo lote só busca quem ainda não tem análise.
        await db.commit()
        total += len(comentarios)
        logger.debug(
            "lote de inferencia gravado id_execucao=%s lote=%s acumulado=%s",
            job.id_execucao,
            len(comentarios),
            total,
        )

    logger.info(
        "inferencia finalizada id_execucao=%s comentarios_analisados=%s", job.id_execucao, total
    )
    return total


async def executar_proximo(db: AsyncSession, classificador: Classificador) -> bool:
    """Reivindica e processa um job. `False` quando não havia nada na fila."""
    job = await fila.reivindicar(db, TIPO_JOB)
    if job is None:
        return False

    try:
        await processar(db, job, classificador)
    except FalhaInferencia as erro:
        # Sem retentativa: ver o cabeçalho do módulo. O rollback descarta apenas o
        # lote em curso — os lotes já commitados ficam, e é isso que o
        # reprocessamento aproveita.
        await _descartar_lote_em_curso(db, job)
        await fila.enviar_para_dlq(db, job, str(erro))
        return True
    except Exception as erro:
        # Rede de segurança: nenhum job pode ficar preso em 'processando'.
        await _descartar_lote_em_curso(db, job)
        logger.exception("falha inesperada na inferencia id_execucao=%s", job.id_execucao)
        await fila.enviar_para_dlq(db, job, f"erro inesperado: {erro!r}")
        return True

    await fila.concluir(db, job)
    return True


async def _descartar_lote_em_curso(db: AsyncSession, job: Job) -> None:
    """Desfaz o lote não commitado e recarrega o job.

    O rollback expira os objetos da sessão; sem o refresh, ler `job.tipo` para montar
    a linha da DLQ dispararia um carregamento preguiçoso fora do contexto assíncrono
    do SQLAlchemy.
    """
    await db.rollback()
    await db.refresh(job)
