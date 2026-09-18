"""Entrypoint do worker de coleta: `python -m app.workers.runner`.

Processo separado da API de propósito — o FastAPI não pode ficar segurando coleta
(CLAUDE.md Seção 5). Dá para subir mais de uma instância: o `SKIP LOCKED` da fila
garante que duas não peguem o mesmo job.
"""

import asyncio
import contextlib
import logging
import signal

import httpx

from app.core.config import settings
from app.core.database import async_session_factory
from app.workers.coleta import executar_proximo
from app.workers.youtube import ClienteYouTube

logger = logging.getLogger(__name__)


async def _ciclo(parar: asyncio.Event, cliente: ClienteYouTube) -> None:
    """Consome a fila até esvaziar, depois dorme o intervalo de polling."""
    while not parar.is_set():
        try:
            async with async_session_factory() as db:
                trabalhou = await executar_proximo(db, cliente)
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

    parar = asyncio.Event()
    laco = asyncio.get_running_loop()
    for sinal in (signal.SIGINT, signal.SIGTERM):
        # Windows não implementa add_signal_handler no proactor loop; lá quem
        # encerra é o KeyboardInterrupt do __main__.
        with contextlib.suppress(NotImplementedError):
            laco.add_signal_handler(sinal, parar.set)

    logger.info(
        "worker de coleta iniciado intervalo=%ss max_tentativas=%s",
        settings.worker_poll_interval_seconds,
        settings.worker_max_retries,
    )

    async with httpx.AsyncClient(timeout=settings.youtube_timeout_seconds) as http:
        cliente = ClienteYouTube(settings.youtube_api_key, http)
        await _ciclo(parar, cliente)

    logger.info("worker de coleta encerrado")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
