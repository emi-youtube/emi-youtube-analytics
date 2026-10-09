"""Entrypoint dos workers: `python -m app.workers.runner`.

Processo separado da API de propósito — o FastAPI não pode ficar segurando coleta nem
inferência (CLAUDE.md Seção 5). Dá para subir mais de uma instância: o `SKIP LOCKED`
da fila garante que duas não peguem o mesmo job.

**Um processo para as três etapas**, e não um por worker. Dentro do escopo do projeto
(500 a 5.000 comentários por execução) as três são curtas: a coleta espera rede, a
inferência e a modelagem de tópicos ocupam processador, e nunca rodam ao mesmo tempo
para a mesma execução. Três serviços custariam mais dois contêineres no crédito do
Azure para não resolver nada — a mesma razão que faz a fila ser uma tabela em vez de um
Redis (CLAUDE.md Seção 10).

**O reaper roda no próprio laço**, sem job agendado e sem serviço à parte: é uma
consulta a cada `worker_reaper_intervalo_segundos` que devolve à fila o job que
um worker morto deixou em `processando` (`workers/fila.devolver_presos`). Em
produção worker morrendo é questão de quando, não de se.

**O expurgo também roda no laço** (`workers/expurgo.py`), a cada
`worker_expurgo_intervalo_segundos`: apaga o texto dos comentários antes dos 30 dias
que as políticas do YouTube permitem e atualiza o título dos vídeos (ADR-015). Falha
dele é registrada e não impede o ciclo de pegar jobs.

**O classificador é carregado ANTES do laço.** É onde o portão da regra 5 do CLAUDE.md
e as conferências de sha256 acontecem. O BERTimbau é o classificador de produção; se
ele não sobe, o léxico assume (`montar_classificador`). Se nem o léxico está lá, o
worker se recusa a subir com uma mensagem que diz o caminho esperado, em vez de coletar
durante horas e falhar na hora de classificar.
"""

import asyncio
import contextlib
import logging
import signal
import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.logs import configurar_logs
from app.inferencia.base import Classificador, ClassificadorIndisponivel
from app.inferencia.bertimbau import ClassificadorBertimbau
from app.inferencia.lexico import ClassificadorLexico
from app.inferencia.versao import ativar_versao
from app.workers import coleta, expurgo, fila, inferencia, topicos
from app.workers.youtube import ClienteYouTube

logger = logging.getLogger(__name__)


async def montar_classificador(db: AsyncSession) -> Classificador:
    """O BERTimbau; se ele não puder subir, o léxico. Os dois passam pelo portão.

    Ponto único de troca: o resto do arquivo não muda, e o `inferencia.py` não fica
    sabendo qual dos dois está em pé.

    **Contingência, não erro fatal.** Pasta ausente, download que falhou, sha256
    diferente, versão de pré-processamento divergente, `torch` ausente — tudo isso vira
    `ClassificadorIndisponivel` no BERTimbau, e o worker cai para o léxico com o motivo
    no log em WARNING. As análises gravadas nesse estado apontam para a linha do
    léxico em VERSOES_MODELO (o descritor é da implementação que classificou), então o
    histórico diz a verdade sobre quem rotulou cada comentário. Um painel com o piso do
    Capítulo 5 é melhor que uma fila parada.

    A troca acontece só na subida: um worker que subiu com o léxico continua com ele
    até reiniciar. Alternar no meio de uma execução misturaria dois classificadores
    nos mesmos resultados.

    Se o léxico também não sobe, aí sim é fatal — sobe a exceção dele.

    **Quem subiu vira a versão `ativo`**, e as demais `arquivado`
    (`inferencia.versao.ativar_versao`): é o que o painel mostra como modelo em uso,
    então em contingência a tela diz léxico, e não o BERTimbau que falhou.
    """
    classificador: Classificador
    try:
        classificador = ClassificadorBertimbau.de_pasta(settings.caminho_bertimbau)
        classificador.validar()
    except ClassificadorIndisponivel as erro:
        logger.warning(
            "BERTimbau indisponivel; usando o lexico como contingencia. Motivo:\n%s", erro
        )
        classificador = ClassificadorLexico.de_arquivo(settings.caminho_sentilex)
        classificador.validar()

    await ativar_versao(db, classificador.descritor)
    return classificador


async def _expurgar(db: AsyncSession, cliente: ClienteYouTube) -> None:
    """Uma passada do expurgo. Nunca derruba o ciclo: tenta de novo no próximo intervalo."""
    try:
        resumo = await expurgo.executar(db, cliente)
    except Exception:
        await db.rollback()
        logger.exception("expurgo falhou; tentando de novo no proximo intervalo")
        return
    if resumo.fez_algo:
        logger.info(
            "expurgo concluido textos_apagados=%s videos_atualizados=%s videos_apagados=%s "
            "execucoes_apagadas=%s",
            resumo.execucoes_com_texto_apagado,
            resumo.videos_atualizados,
            resumo.videos_apagados,
            resumo.execucoes_apagadas,
        )


async def _ciclo(parar: asyncio.Event, cliente: ClienteYouTube, classificador: Classificador):
    """Consome a fila até esvaziar, depois dorme o intervalo de polling.

    A ordem das tentativas segue a cadeia (coleta -> inferência -> tópicos) porque
    cada etapa produz o que a seguinte consome: com as filas cheias, adiantar a
    etapa de baixo encurta o tempo total da execução que o usuário está esperando.
    """
    proximo_reaper = 0.0
    proximo_expurgo = 0.0

    while not parar.is_set():
        try:
            async with async_session_factory() as db:
                # O reaper vem antes de reivindicar: um job devolvido nesta
                # passagem já pode ser pego na mesma volta do laço.
                agora = time.monotonic()
                if agora >= proximo_reaper:
                    proximo_reaper = agora + settings.worker_reaper_intervalo_segundos
                    devolvidos = await fila.devolver_presos(
                        db,
                        settings.worker_timeout_job_minutos,
                        settings.worker_max_retries,
                    )
                    if devolvidos:
                        logger.warning("reaper tratou %s job(s) preso(s)", devolvidos)

                if agora >= proximo_expurgo:
                    proximo_expurgo = agora + settings.worker_expurgo_intervalo_segundos
                    await _expurgar(db, cliente)

                trabalhou = await coleta.executar_proximo(db, cliente)
                if not trabalhou:
                    trabalhou = await inferencia.executar_proximo(db, classificador)
                if not trabalhou:
                    trabalhou = await topicos.executar_proximo(db)
        except Exception:
            # Falha de infraestrutura (banco fora do ar, por exemplo): não derruba
            # o worker, que volta a tentar no próximo ciclo.
            logger.exception("ciclo do worker falhou; tentando de novo no proximo intervalo")
            trabalhou = False

        if trabalhou:
            continue

        # Fila vazia: espera o intervalo, mas acorda na hora se pedirem parada.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(parar.wait(), timeout=settings.worker_poll_interval_seconds)


async def main() -> None:
    # A mesma configuração da API (core/logs.py), inclusive o silêncio do httpx, que
    # é a segunda camada da proteção da chave do YouTube.
    configurar_logs(settings.log_level)

    try:
        async with async_session_factory() as db:
            classificador = await montar_classificador(db)
    except ClassificadorIndisponivel as erro:
        # Recurso ausente ou trocado não é falha transitória: não há o que tentar de
        # novo no próximo ciclo. Sai com mensagem acionável em vez de subir um worker
        # que coletaria sem nunca classificar.
        logger.error("worker nao pode iniciar sem classificador:\n%s", erro)
        raise SystemExit(1) from erro

    parar = asyncio.Event()
    laco = asyncio.get_running_loop()
    for sinal in (signal.SIGINT, signal.SIGTERM):
        # Windows não implementa add_signal_handler no proactor loop; lá quem
        # encerra é o KeyboardInterrupt do __main__.
        with contextlib.suppress(NotImplementedError):
            laco.add_signal_handler(sinal, parar.set)

    logger.info(
        "workers iniciados etapas=coleta,inferencia,topicos classificador=%s %s intervalo=%ss "
        "max_tentativas=%s reaper=a cada %ss com limite de %smin expurgo=a cada %ss",
        classificador.descritor.nome_modelo,
        classificador.descritor.versao,
        settings.worker_poll_interval_seconds,
        settings.worker_max_retries,
        settings.worker_reaper_intervalo_segundos,
        settings.worker_timeout_job_minutos,
        settings.worker_expurgo_intervalo_segundos,
    )

    async with httpx.AsyncClient(timeout=settings.youtube_timeout_seconds) as http:
        cliente = ClienteYouTube(settings.youtube_api_key, http)
        await _ciclo(parar, cliente, classificador)

    logger.info("workers encerrados")


if __name__ == "__main__":
    # `suppress` pega só o KeyboardInterrupt (Ctrl+C é encerramento normal aqui). O
    # SystemExit(1) do classificador indisponível passa direto e o processo sai 1 —
    # é o que um supervisor precisa ver para não ficar reiniciando em laço.
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
