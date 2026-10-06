"""Rotação de refresh token, troca de senha e recuperação de senha."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.security import hash_token
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.token_redefinicao_senha import TokenRedefinicaoSenha
from app.services import email as email_service
from app.services.auth import LINK_REDEFINICAO_INVALIDO, MAX_TENTATIVAS
from tests.conftest import autenticar

EMAIL = "pme@exemplo.com"
SENHA = "SenhaForte123"
NOVA = "OutraSenha456"


async def logar(cliente, email: str = EMAIL, senha: str = SENHA):
    return await cliente.post("/api/v1/auth/login", json={"email": email, "senha": senha})


async def conta_logada(cliente) -> dict:
    await autenticar(cliente, EMAIL, SENHA)
    resposta = await logar(cliente)
    assert resposta.status_code == 200
    return resposta.json()


async def refresh(cliente, token: str):
    return await cliente.post("/api/v1/auth/refresh", json={"refresh_token": token})


class CaixaDeSaida:
    """Dublê do envio de e-mail: guarda o que seria enviado."""

    def __init__(self) -> None:
        self.mensagens: list[tuple[str, str, str]] = []

    async def enviar(self, destinatario: str, assunto: str, texto: str) -> None:
        self.mensagens.append((destinatario, assunto, texto))

    def token_de_redefinicao(self) -> str:
        texto = self.mensagens[-1][2]
        return texto.split("token=")[1].split()[0]


def caixa(monkeypatch) -> CaixaDeSaida:
    saida = CaixaDeSaida()
    monkeypatch.setattr(email_service, "enviar", saida.enviar)
    return saida


# --------------------------------------------------------------------------- rotação


async def test_refresh_devolve_par_novo_e_invalida_o_antigo(cliente):
    tokens = await conta_logada(cliente)

    primeira = await refresh(cliente, tokens["refresh_token"])

    assert primeira.status_code == 200
    novo = primeira.json()
    assert novo["refresh_token"] != tokens["refresh_token"]
    assert (await refresh(cliente, novo["refresh_token"])).status_code == 200


async def test_cadeia_de_rotacoes_funciona(cliente):
    atual = (await conta_logada(cliente))["refresh_token"]
    for _ in range(5):
        resposta = await refresh(cliente, atual)
        assert resposta.status_code == 200
        atual = resposta.json()["refresh_token"]


async def test_reuso_de_refresh_derruba_a_familia(cliente, sessao, caplog):
    tokens = await conta_logada(cliente)
    outra_sessao = (await logar(cliente)).json()["refresh_token"]  # outro dispositivo
    sucessor = (await refresh(cliente, tokens["refresh_token"])).json()["refresh_token"]

    with caplog.at_level(logging.WARNING, logger="app.services.auth"):
        reuso = await refresh(cliente, tokens["refresh_token"])

    assert reuso.status_code == 401
    # Toda a família cai: o sucessor legítimo e a sessão do outro dispositivo.
    assert (await refresh(cliente, sucessor)).status_code == 401
    assert (await refresh(cliente, outra_sessao)).status_code == 401
    ativos = await sessao.scalar(
        select(func.count())
        .select_from(TokenAtualizacao)
        .where(TokenAtualizacao.revogado.is_(False))
    )
    assert ativos == 0
    assert any("evento=refresh_token_reuso" in r.getMessage() for r in caplog.records)


async def test_depois_do_reuso_o_login_volta_a_funcionar(cliente):
    tokens = await conta_logada(cliente)
    await refresh(cliente, tokens["refresh_token"])
    await refresh(cliente, tokens["refresh_token"])  # reuso

    novo = await logar(cliente)

    assert novo.status_code == 200
    assert (await refresh(cliente, novo.json()["refresh_token"])).status_code == 200


async def test_logout_de_token_ja_trocado_e_tratado_como_reuso(cliente):
    tokens = await conta_logada(cliente)
    sucessor = (await refresh(cliente, tokens["refresh_token"])).json()["refresh_token"]

    resposta = await cliente.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )

    assert resposta.status_code == 401
    assert (await refresh(cliente, sucessor)).status_code == 401


async def test_refresh_vencido_e_podado_no_proximo_login(cliente, sessao):
    """Regra 7: a rotação deixa uma linha por refresh; as vencidas saem na escrita."""
    await conta_logada(cliente)
    registro = await sessao.scalar(select(TokenAtualizacao))
    registro.expira_em = datetime.now(UTC) - timedelta(days=1)
    await sessao.commit()
    id_vencido = registro.id_token

    await logar(cliente)

    sessao.expire_all()
    assert await sessao.get(TokenAtualizacao, id_vencido) is None


# --------------------------------------------------------------------------- troca de senha


async def trocar(cliente, access: str, atual: str = SENHA, nova: str = NOVA):
    return await cliente.post(
        "/api/v1/auth/trocar-senha",
        json={"senha_atual": atual, "nova_senha": nova},
        headers={"Authorization": f"Bearer {access}"},
    )


async def test_trocar_senha_revoga_refresh_e_devolve_par_novo(cliente):
    tokens = await conta_logada(cliente)
    outra_sessao = (await logar(cliente)).json()["refresh_token"]

    resposta = await trocar(cliente, tokens["access_token"])

    assert resposta.status_code == 200
    assert (await refresh(cliente, tokens["refresh_token"])).status_code == 401
    assert (await refresh(cliente, outra_sessao)).status_code == 401
    assert (await refresh(cliente, resposta.json()["refresh_token"])).status_code == 200
    assert (await logar(cliente, senha=SENHA)).status_code == 401
    assert (await logar(cliente, senha=NOVA)).status_code == 200


async def test_trocar_senha_exige_a_atual(cliente, sessao):
    tokens = await conta_logada(cliente)

    resposta = await trocar(cliente, tokens["access_token"], atual="errada-123")

    assert resposta.status_code == 400
    # Conta no mesmo contador do login.
    assert await sessao.scalar(select(func.count()).select_from(TentativaLogin)) == 1
    assert (await refresh(cliente, tokens["refresh_token"])).status_code == 200


async def test_trocar_senha_bloqueia_apos_tentativas(cliente):
    tokens = await conta_logada(cliente)
    for _ in range(MAX_TENTATIVAS):
        await trocar(cliente, tokens["access_token"], atual="errada-123")

    resposta = await trocar(cliente, tokens["access_token"])

    assert resposta.status_code == 429


async def test_trocar_senha_aplica_a_politica_de_forca(cliente):
    tokens = await conta_logada(cliente)

    resposta = await trocar(cliente, tokens["access_token"], nova="curta")

    assert resposta.status_code == 422
    assert "curta" not in resposta.text


async def test_trocar_senha_exige_login(cliente):
    resposta = await cliente.post(
        "/api/v1/auth/trocar-senha", json={"senha_atual": SENHA, "nova_senha": NOVA}
    )

    assert resposta.status_code == 401


# --------------------------------------------------------------------------- recuperação


async def esqueci(cliente, email: str = EMAIL, ip: str = "203.0.113.7"):
    return await cliente.post(
        "/api/v1/auth/esqueci-senha", json={"email": email}, headers={"X-Forwarded-For": ip}
    )


async def test_esqueci_senha_responde_igual_com_e_sem_conta(cliente, monkeypatch):
    saida = caixa(monkeypatch)
    await conta_logada(cliente)

    com_conta = await esqueci(cliente, EMAIL)
    sem_conta = await esqueci(cliente, "ninguem@exemplo.com")

    assert com_conta.status_code == sem_conta.status_code == 202
    assert com_conta.json() == sem_conta.json()
    assert com_conta.headers.get("content-length") == sem_conta.headers.get("content-length")
    # Só quem tem conta recebe e-mail.
    assert [m[0] for m in saida.mensagens] == [EMAIL]


async def test_redefinir_senha_pelo_link(cliente, sessao, monkeypatch):
    saida = caixa(monkeypatch)
    tokens = await conta_logada(cliente)
    await esqueci(cliente)
    token = saida.token_de_redefinicao()

    resposta = await cliente.post(
        "/api/v1/auth/redefinir-senha", json={"token": token, "nova_senha": NOVA}
    )

    assert resposta.status_code == 204
    assert (await logar(cliente, senha=NOVA)).status_code == 200
    # Revoga as sessões abertas antes da redefinição.
    assert (await refresh(cliente, tokens["refresh_token"])).status_code == 401
    registro = await sessao.scalar(select(TokenRedefinicaoSenha))
    assert registro.token_hash == hash_token(token)


async def test_link_de_redefinicao_e_de_uso_unico(cliente, monkeypatch):
    saida = caixa(monkeypatch)
    await conta_logada(cliente)
    await esqueci(cliente)
    token = saida.token_de_redefinicao()
    corpo = {"token": token, "nova_senha": NOVA}
    await cliente.post("/api/v1/auth/redefinir-senha", json=corpo)

    resposta = await cliente.post(
        "/api/v1/auth/redefinir-senha", json={"token": token, "nova_senha": "Terceira789"}
    )

    assert resposta.status_code == 400
    assert resposta.json()["detail"] == LINK_REDEFINICAO_INVALIDO


async def test_link_de_redefinicao_expira(cliente, sessao, monkeypatch):
    saida = caixa(monkeypatch)
    await conta_logada(cliente)
    await esqueci(cliente)
    registro = await sessao.scalar(select(TokenRedefinicaoSenha))
    registro.expira_em = datetime.now(UTC) - timedelta(seconds=1)
    await sessao.commit()

    resposta = await cliente.post(
        "/api/v1/auth/redefinir-senha",
        json={"token": saida.token_de_redefinicao(), "nova_senha": NOVA},
    )

    assert resposta.status_code == 400


async def test_link_adulterado_e_recusado(cliente, monkeypatch):
    saida = caixa(monkeypatch)
    await conta_logada(cliente)
    await esqueci(cliente)

    resposta = await cliente.post(
        "/api/v1/auth/redefinir-senha",
        json={"token": saida.token_de_redefinicao() + "x", "nova_senha": NOVA},
    )

    assert resposta.status_code == 400


async def test_novo_pedido_invalida_o_link_anterior(cliente, monkeypatch):
    saida = caixa(monkeypatch)
    await conta_logada(cliente)
    await esqueci(cliente)
    antigo = saida.token_de_redefinicao()
    await esqueci(cliente)

    resposta = await cliente.post(
        "/api/v1/auth/redefinir-senha", json={"token": antigo, "nova_senha": NOVA}
    )

    assert resposta.status_code == 400
    novo = saida.token_de_redefinicao()
    assert (
        await cliente.post("/api/v1/auth/redefinir-senha", json={"token": novo, "nova_senha": NOVA})
    ).status_code == 204


async def test_redefinir_zera_o_bloqueio(cliente, monkeypatch):
    saida = caixa(monkeypatch)
    await conta_logada(cliente)
    for _ in range(MAX_TENTATIVAS):
        await logar(cliente, senha="errada-123")
    assert (await logar(cliente)).status_code == 429

    await esqueci(cliente)
    await cliente.post(
        "/api/v1/auth/redefinir-senha",
        json={"token": saida.token_de_redefinicao(), "nova_senha": NOVA},
    )

    assert (await logar(cliente, senha=NOVA)).status_code == 200


async def test_esqueci_senha_limita_por_conta_em_silencio(cliente, monkeypatch):
    saida = caixa(monkeypatch)
    await conta_logada(cliente)

    respostas = [await esqueci(cliente, ip=f"198.51.100.{i}") for i in range(5)]

    assert {r.status_code for r in respostas} == {202}
    assert len(saida.mensagens) == 3


async def test_esqueci_senha_limita_por_ip(cliente, monkeypatch):
    caixa(monkeypatch)

    respostas = [await esqueci(cliente, f"pessoa{i}@exemplo.com") for i in range(6)]

    assert [r.status_code for r in respostas[:5]] == [202] * 5
    assert respostas[5].status_code == 429
    assert "Retry-After" in respostas[5].headers
    # Outro IP segue livre.
    assert (await esqueci(cliente, ip="192.0.2.1")).status_code == 202


async def test_ip_vem_do_ultimo_item_do_x_forwarded_for(cliente, monkeypatch):
    """Os primeiros itens vêm do cliente e podem ser forjados para fugir do limite."""
    caixa(monkeypatch)
    for i in range(5):
        await esqueci(cliente, ip=f"10.0.0.{i}, 203.0.113.9:4455")

    resposta = await esqueci(cliente, ip="10.9.9.9, 203.0.113.9:5566")

    assert resposta.status_code == 429


# --------------------------------------------------------------------------- envio de e-mail


async def test_email_em_modo_log_escreve_no_log_em_desenvolvimento(monkeypatch, caplog):
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_provedor", "log")
    monkeypatch.setattr(settings, "app_env", "development")

    with caplog.at_level(logging.INFO, logger="app.services.email"):
        await email_service.enviar("a@b.com", "Assunto", "link: http://x/?token=abc")

    assert "token=abc" in caplog.text


async def test_email_sem_provedor_em_producao_nao_vaza_o_link(monkeypatch, caplog):
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_provedor", "log")
    monkeypatch.setattr(settings, "app_env", "production")

    with caplog.at_level(logging.INFO, logger="app.services.email"):
        await email_service.enviar("a@b.com", "Assunto", "link: http://x/?token=abc")

    assert "token=abc" not in caplog.text
    assert "a@b.com" not in caplog.text
    assert "NAO enviado" in caplog.text
