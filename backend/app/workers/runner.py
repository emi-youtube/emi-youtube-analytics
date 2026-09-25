"""Entrypoint dos workers: `python -m app.workers.runner`.

Processo separado da API de propósito — o FastAPI não pode ficar segurando coleta nem
inferência (CLAUDE.md Seção 5). Dá para subir mais de uma instância: o `SKIP LOCKED`
da fila garante que duas não peguem o mesmo job.

**Um processo para as duas etapas**, e não um por worker. Dentro do escopo do projeto
(500 a 5.000 comentários por execução) as duas são curtas e nunca disputam recurso: a
coleta espera rede, a inferência ocupa processador. Dois serviços custariam outro
contêiner no crédito do Azure para não resolver nada — a mesma razão que faz a fila ser
uma tabela em vez de um Redis (CLAUDE.md Seção 10).

**O classificador é carregado ANTES do laço.** É onde o portão da regra 5 do CLAUDE.md
e a conferência do sha256 do léxico acontecem: se o recurso não está lá, o worker se
recusa a subir com uma mensagem que diz o caminho esperado, em vez de coletar durante
horas e falhar na hora de classificar.
"""

import asyncio
import contextlib
import logging
import signal

import httpx

from app.core.config import settings
from app.core.database import async_session_factory
from app.inferencia.base import Classificador, ClassificadorIndisponivel
from app.inferencia.lexico import ClassificadorLexico
from app.workers import coleta, inferencia
from app.workers.youtube import ClienteYouTube

logger = logging.getLogger(__name__)


def montar_classificador() -> Classificador:
    """Carrega a implementação em pé e roda o portão da versão do pré-processamento.

    Ponto único de troca: quando o BERTimbau oficial existir, é esta função que passa a
    devolver `ClassificadorBertimbau.de_pasta(...)` — o resto do arquivo não muda, e o
    `inferencia.py` não fica sabendo.
    """
    classificador = ClassificadorLexico.de_arquivo(settings.caminho_sentilex)
    classificador.validar()
    return classificador


async def _ciclo(parar: asyncio.Event, cliente: ClienteYouTube, classificador: Classificador):
    """Consome a fila até esvaziar, depois dorme o intervalo de polling.

    A coleta vem primeiro em cada volta porque é ela que produz o que a inferência
    consome: com as duas filas cheias, adiantar a coleta encurta o tempo total da
    execução que o usuário está esperando.
    """
    while not parar.is_set():
        try:
            async with async_session_factory() as db:
                trabalhou = await coleta.executar_proximo(db, cliente)
                if not trabalhou:
                    trabalhou = await inferencia.executar_proximo(db, classificador)
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
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Segunda camada da proteção da chave: em INFO o httpx loga a URL completa de
    # cada requisição. Hoje a chave vai no cabeçalho (workers/youtube.py), então a
    # URL já não a contém — mas qualquer parâmetro sensível que venha a entrar na
    # query cairia no log de novo. WARNING mantém erro de rede visível e cala o resto.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    try:
        classificador = montar_classificador()
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
        "workers iniciados etapas=coleta,inferencia classificador=%s %s intervalo=%ss "
        "max_tentativas=%s",
        classificador.descritor.nome_modelo,
        classificador.descritor.versao,
        settings.worker_poll_interval_seconds,
        settings.worker_max_retries,
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
