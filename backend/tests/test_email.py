"""Envio de e-mail pelo provedor SMTP (services/email.py).

Nenhum teste abre conexão: `smtplib.SMTP` é trocado por um dublê que registra o que
o envio fez.
"""

import logging
import smtplib
from typing import ClassVar

import pytest

from app.core import config
from app.services import email as email_service

USUARIO = "emi.youtube.analytics@gmail.com"
SENHA_DE_APP = "abcd efgh ijkl mnop"


class SmtpFalso:
    """Faz o papel de `smtplib.SMTP` como gerenciador de contexto."""

    instancias: ClassVar[list["SmtpFalso"]] = []
    falhar_no_login: ClassVar[bool] = False

    def __init__(self, host: str, porta: int, timeout: float) -> None:
        self.host, self.porta, self.timeout = host, porta, timeout
        self.tls = False
        self.login_feito: tuple[str, str] | None = None
        self.enviadas: list = []
        SmtpFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self, context=None) -> None:
        self.tls = context is not None

    def login(self, usuario: str, senha: str) -> None:
        if SmtpFalso.falhar_no_login:
            raise smtplib.SMTPAuthenticationError(535, b"senha recusada " + senha.encode())
        self.login_feito = (usuario, senha)

    def send_message(self, mensagem) -> None:
        self.enviadas.append(mensagem)


@pytest.fixture
def smtp(monkeypatch):
    SmtpFalso.instancias = []
    SmtpFalso.falhar_no_login = False
    monkeypatch.setattr(email_service.smtplib, "SMTP", SmtpFalso)
    monkeypatch.setattr(
        email_service,
        "settings",
        config.settings.model_copy(
            update={
                "email_provedor": "smtp",
                "smtp_host": "smtp.gmail.com",
                "smtp_porta": 587,
                "smtp_usuario": USUARIO,
                "smtp_senha": SENHA_DE_APP,
                "app_env": "production",
            }
        ),
    )
    return SmtpFalso


async def test_smtp_envia_com_tls_login_e_remetente_da_conta(smtp):
    await email_service.enviar("cliente@exemplo.com", "Assunto", "Corpo com link")

    [conexao] = smtp.instancias
    assert (conexao.host, conexao.porta) == ("smtp.gmail.com", 587)
    assert conexao.tls is True
    # A senha de app vem do Google em grupos de 4; os espaços saem.
    assert conexao.login_feito == (USUARIO, "abcdefghijklmnop")
    [mensagem] = conexao.enviadas
    assert mensagem["From"] == f"Emi Analytics <{USUARIO}>"
    assert mensagem["To"] == "cliente@exemplo.com"
    assert mensagem["Subject"] == "Assunto"
    assert "Corpo com link" in mensagem.get_content()


async def test_falha_do_smtp_nao_levanta_nem_vaza_a_senha(smtp, caplog):
    smtp.falhar_no_login = True

    with caplog.at_level(logging.INFO, logger="app.services.email"):
        await email_service.enviar("cliente@exemplo.com", "Assunto", "Corpo")

    assert "falha ao enviar e-mail provedor=smtp" in caplog.text
    assert "SMTPAuthenticationError" in caplog.text
    assert "abcd" not in caplog.text
    assert "cliente@exemplo.com" not in caplog.text


async def test_smtp_sem_senha_em_producao_nao_envia_e_avisa(smtp, monkeypatch, caplog):
    monkeypatch.setattr(
        email_service,
        "settings",
        email_service.settings.model_copy(update={"smtp_senha": ""}),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.email"):
        await email_service.enviar("cliente@exemplo.com", "Assunto", "Corpo")

    assert smtp.instancias == []
    assert "e-mail NAO enviado" in caplog.text
