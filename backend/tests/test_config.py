"""Avisos de configuração no arranque da API."""

import logging

import pytest

from app.core import config
from app.core.config import AVISO_FRONTEND_URL_LOCAL, avisar_configuracao_suspeita
from app.main import app, lifespan


@pytest.mark.parametrize(
    "url", ["http://localhost:4200", "http://127.0.0.1:4200", "https://localhost"]
)
def test_producao_com_frontend_url_local_avisa(url, caplog):
    cfg = config.settings.model_copy(update={"app_env": "production", "frontend_url": url})

    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        assert avisar_configuracao_suspeita(cfg) is True

    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in avisos] == [AVISO_FRONTEND_URL_LOCAL]
    assert "localhost em produção" in AVISO_FRONTEND_URL_LOCAL


def test_producao_com_dominio_real_nao_avisa(caplog):
    cfg = config.settings.model_copy(
        update={"app_env": "production", "frontend_url": "https://emi.vercel.app"}
    )

    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        assert avisar_configuracao_suspeita(cfg) is False

    assert caplog.records == []


def test_desenvolvimento_com_localhost_nao_avisa(caplog):
    cfg = config.settings.model_copy(
        update={"app_env": "development", "frontend_url": "http://localhost:4200"}
    )

    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        assert avisar_configuracao_suspeita(cfg) is False

    assert caplog.records == []


async def test_o_arranque_da_api_avisa_e_nao_derruba(monkeypatch, caplog):
    monkeypatch.setattr(
        "app.main.settings",
        config.settings.model_copy(
            update={"app_env": "production", "frontend_url": "http://localhost:4200"}
        ),
    )

    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        async with lifespan(app):
            pass  # subiu: o aviso não é exceção

    assert AVISO_FRONTEND_URL_LOCAL in caplog.text
