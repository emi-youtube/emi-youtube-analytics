"""Log da API: os `logger.info` dos serviços precisam sair (core/logs.py)."""

import logging

import pytest

from app.core.logs import configurar_logs
from app.main import app, lifespan


@pytest.fixture
def raiz_limpo():
    """Raiz sem handler, como o uvicorn o deixa; restaura o estado no fim."""
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    nivel_httpx = logging.getLogger("httpx").level
    raiz.handlers.clear()
    raiz.setLevel(logging.WARNING)
    yield raiz
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)
    logging.getLogger("httpx").setLevel(nivel_httpx)


def test_sem_configurar_info_dos_servicos_some(raiz_limpo):
    # O defeito que a correção cobre: com o raiz em WARNING, INFO não passa.
    assert not logging.getLogger("app.services.conta").isEnabledFor(logging.INFO)


def test_configurar_liga_info_e_cala_httpx(raiz_limpo):
    configurar_logs("INFO")

    assert logging.getLogger("app.services.conta").isEnabledFor(logging.INFO)
    assert raiz_limpo.handlers, "o raiz precisa de um handler para as linhas saírem"
    assert logging.getLogger("httpx").level == logging.WARNING


def test_configurar_respeita_o_nivel_pedido(raiz_limpo):
    configurar_logs("WARNING")

    assert not logging.getLogger("app.services.conta").isEnabledFor(logging.INFO)


async def test_arranque_da_api_configura_o_log(raiz_limpo):
    async with lifespan(app):
        assert logging.getLogger("app.services.empresa").isEnabledFor(logging.INFO)
