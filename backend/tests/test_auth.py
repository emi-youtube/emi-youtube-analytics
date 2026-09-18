"""Testes do UC01 / RF01 — cadastro, login, refresh e autorização."""

import logging
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_token
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.usuario import Usuario
from app.services.auth import (
    CREDENCIAIS_INVALIDAS,
    MAX_TENTATIVAS,
    RETENCAO_TENTATIVAS,
    _as_utc,
)

from .conftest import ROTA_ADMIN

EMAIL = "pme@exemplo.com"
SENHA = "SenhaForte123"
NOME = "Loja Exemplo"


async def registrar(cliente: AsyncClient, email: str = EMAIL, senha: str = SENHA, **extra):
    corpo = {"nome": NOME, "email": email, "senha": senha, **extra}
    return await cliente.post("/api/v1/auth/registrar", json=corpo)


async def logar(cliente: AsyncClient, email: str = EMAIL, senha: str = SENHA):
    return await cliente.post("/api/v1/auth/login", json={"email": email, "senha": senha})


async def registrar_e_logar(cliente: AsyncClient) -> dict:
    await registrar(cliente)
    resposta = await logar(cliente)
    assert resposta.status_code == 200
    return resposta.json()


async def semear_falhas(sessao, email: str, instantes: list[datetime]) -> None:
    """Insere tentativas malsucedidas com data controlada, sem esperar o relógio.

    Recebe o e-mail em texto plano e hasheia aqui, como o serviço faz.
    """
    for instante in instantes:
        sessao.add(TentativaLogin(email_hash=hash_token(email), tentado_em=instante))
    await sessao.commit()


# --------------------------------------------------------------------------- cadastro


async def test_registrar_cria_usuario_com_papel_pme(cliente):
    resposta = await registrar(cliente)

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["email"] == EMAIL
    assert corpo["papel"] == "usuario_pme"
    assert "senha_hash" not in corpo
    assert "senha" not in corpo


async def test_registrar_persiste_senha_com_hash_bcrypt(cliente, sessao):
    await registrar(cliente)

    usuario = await sessao.scalar(select(Usuario).where(Usuario.email == EMAIL))
    assert usuario.senha_hash != SENHA
    assert usuario.senha_hash.startswith("$2b$")


async def test_registrar_ignora_papel_enviado_pelo_cliente(cliente):
    """Aceitar `papel` do corpo permitiria alguém se cadastrar como admin."""
    resposta = await registrar(cliente, papel="admin")

    assert resposta.status_code == 201
    assert resposta.json()["papel"] == "usuario_pme"


async def test_registrar_email_duplicado_retorna_409(cliente):
    await registrar(cliente)
    resposta = await registrar(cliente)

    assert resposta.status_code == 409


async def test_registrar_normaliza_email_para_minusculas(cliente):
    resposta = await registrar(cliente, email="PME@Exemplo.COM")

    assert resposta.status_code == 201
    assert resposta.json()["email"] == EMAIL


async def test_registrar_rejeita_senha_curta(cliente):
    resposta = await registrar(cliente, senha="curta")

    assert resposta.status_code == 422


async def test_erro_de_validacao_nao_devolve_a_senha(cliente):
    """A senha não pode vazar nem no corpo do erro 422 do Pydantic."""
    senha = "abc"
    resposta = await registrar(cliente, senha=senha)

    assert resposta.status_code == 422
    assert senha not in resposta.text


async def test_erro_de_validacao_ainda_indica_o_campo(cliente):
    """Esconder `input` não pode cegar o frontend sobre qual campo falhou."""
    resposta = await registrar(cliente, senha="abc")

    erro = resposta.json()["detail"][0]
    assert erro["loc"][-1] == "senha"
    assert erro["msg"]


# --------------------------------------------------------------------------- login


async def test_login_retorna_par_de_tokens(cliente):
    tokens = await registrar_e_logar(cliente)

    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]


async def test_prazos_dos_tokens_seguem_a_configuracao(cliente):
    tokens = await registrar_e_logar(cliente)

    access = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    refresh = jwt.decode(tokens["refresh_token"], options={"verify_signature": False})

    assert access["exp"] - access["iat"] == settings.jwt_access_token_expire_minutes * 60
    assert refresh["exp"] - refresh["iat"] == settings.jwt_refresh_token_expire_days * 86400
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"


async def test_login_persiste_hash_do_refresh_e_nao_o_token(cliente, sessao):
    tokens = await registrar_e_logar(cliente)

    registro = await sessao.scalar(select(TokenAtualizacao))
    assert registro.revogado is False
    assert registro.token_hash != tokens["refresh_token"]
    assert len(registro.token_hash) == 64


async def test_login_com_senha_errada_retorna_erro_generico(cliente):
    await registrar(cliente)
    resposta = await logar(cliente, senha="SenhaErrada123")

    assert resposta.status_code == 401
    assert resposta.json()["detail"] == CREDENCIAIS_INVALIDAS


async def test_erro_identico_para_email_inexistente_e_senha_errada(cliente):
    """UC01: a resposta não pode revelar se a conta existe."""
    await registrar(cliente)

    senha_errada = await logar(cliente, senha="SenhaErrada123")
    email_inexistente = await logar(cliente, email="ninguem@exemplo.com")

    assert senha_errada.status_code == email_inexistente.status_code == 401
    assert senha_errada.json() == email_inexistente.json()


# --------------------------------------------------------------------------- bloqueio UC01


async def test_bloqueia_apos_cinco_falhas_em_dez_minutos(cliente):
    await registrar(cliente)

    for _ in range(MAX_TENTATIVAS):
        assert (await logar(cliente, senha="SenhaErrada123")).status_code == 401

    bloqueado = await logar(cliente, senha="SenhaErrada123")
    assert bloqueado.status_code == 429
    assert int(bloqueado.headers["Retry-After"]) > 0


async def test_bloqueio_vale_mesmo_com_a_senha_correta(cliente):
    """Senha correta não pode furar o bloqueio, senão ele não protege contra força bruta."""
    await registrar(cliente)
    for _ in range(MAX_TENTATIVAS):
        await logar(cliente, senha="SenhaErrada123")

    resposta = await logar(cliente, senha=SENHA)

    assert resposta.status_code == 429


async def test_bloqueio_vale_para_email_sem_cadastro(cliente):
    """Se só e-mails cadastrados bloqueassem, o 429 viraria oráculo de existência."""
    for _ in range(MAX_TENTATIVAS):
        await logar(cliente, email="ninguem@exemplo.com", senha="qualquer-coisa")

    resposta = await logar(cliente, email="ninguem@exemplo.com", senha="qualquer-coisa")

    assert resposta.status_code == 429


async def test_cinco_falhas_espalhadas_alem_da_janela_nao_bloqueiam(cliente, sessao):
    await registrar(cliente)
    agora = datetime.now(UTC)
    await semear_falhas(
        sessao,
        EMAIL,
        [agora - timedelta(minutes=m) for m in (40, 32, 24, 16, 8)],
    )

    resposta = await logar(cliente)

    assert resposta.status_code == 200


async def test_bloqueio_expira_apos_quinze_minutos(cliente, sessao):
    await registrar(cliente)
    agora = datetime.now(UTC)
    # 5 falhas dentro da janela, porém velhas: o bloqueio de 15 min já terminou
    await semear_falhas(
        sessao,
        EMAIL,
        [agora - timedelta(minutes=20, seconds=s) for s in (40, 30, 20, 10, 0)],
    )

    resposta = await logar(cliente)

    assert resposta.status_code == 200


async def test_login_bem_sucedido_zera_o_contador(cliente, sessao):
    await registrar(cliente)
    for _ in range(MAX_TENTATIVAS - 1):
        await logar(cliente, senha="SenhaErrada123")

    assert (await logar(cliente)).status_code == 200

    restantes = await sessao.scalars(
        select(TentativaLogin).where(TentativaLogin.email_hash == hash_token(EMAIL))
    )
    assert restantes.all() == []


async def test_tentativa_grava_hash_e_nunca_o_email_em_texto_plano(cliente, sessao):
    """A tabela registra tentativa de quem nem tem conta — não pode virar lista de e-mails."""
    await registrar(cliente)
    await logar(cliente, senha="SenhaErrada123")

    linhas = (await sessao.scalars(select(TentativaLogin))).all()
    assert len(linhas) == 1
    assert linhas[0].email_hash == hash_token(EMAIL)
    assert EMAIL not in str(linhas[0].__dict__)


async def test_a_retencao_de_tentativas_e_de_24h():
    assert timedelta(hours=24) == RETENCAO_TENTATIVAS


async def test_nova_falha_poda_tentativas_com_mais_de_24h(cliente, sessao):
    """Horas absolutas de propósito: se a retenção mudar, este teste precisa acusar."""
    await registrar(cliente)
    agora = datetime.now(UTC)
    ha_25h = agora - timedelta(hours=25)
    ha_23h = agora - timedelta(hours=23)
    await semear_falhas(sessao, EMAIL, [ha_25h, ha_23h])

    await logar(cliente, senha="SenhaErrada123")

    restantes = await sessao.scalars(
        select(TentativaLogin.tentado_em).where(TentativaLogin.email_hash == hash_token(EMAIL))
    )
    guardadas = sorted(_as_utc(t) for t in restantes)

    # a de 25h sai; a de 23h fica, junto com a falha recém-registrada
    assert len(guardadas) == 2
    assert abs(guardadas[0] - ha_23h) < timedelta(seconds=1)
    assert abs(guardadas[1] - agora) < timedelta(seconds=5)


async def test_poda_nao_alcanca_outros_emails(cliente, sessao):
    """A poda é por e-mail: não pode apagar histórico de outra conta."""
    await registrar(cliente)
    antiga_de_outro = datetime.now(UTC) - timedelta(hours=48)
    await semear_falhas(sessao, "outro@exemplo.com", [antiga_de_outro])

    await logar(cliente, senha="SenhaErrada123")

    outros = await sessao.scalars(
        select(TentativaLogin).where(
            TentativaLogin.email_hash == hash_token("outro@exemplo.com")
        )
    )
    assert len(outros.all()) == 1


# --------------------------------------------------------------------------- refresh


async def test_refresh_devolve_novo_access_token(cliente):
    tokens = await registrar_e_logar(cliente)

    resposta = await cliente.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert resposta.status_code == 200
    novo = resposta.json()["access_token"]
    assert jwt.decode(novo, options={"verify_signature": False})["type"] == "access"


async def test_refresh_recusa_access_token(cliente):
    """Trocar os tipos de token não pode funcionar."""
    tokens = await registrar_e_logar(cliente)

    resposta = await cliente.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )

    assert resposta.status_code == 401


async def test_refresh_recusa_token_invalido(cliente):
    resposta = await cliente.post("/api/v1/auth/refresh", json={"refresh_token": "nao-e-um-jwt"})

    assert resposta.status_code == 401


async def test_refresh_recusa_token_assinado_com_outro_segredo(cliente):
    forjado = jwt.encode(
        {
            "sub": "1",
            "type": "refresh",
            "exp": datetime.now(UTC) + timedelta(days=1),
            "iat": datetime.now(UTC),
        },
        "outro-segredo",
        algorithm="HS256",
    )

    resposta = await cliente.post("/api/v1/auth/refresh", json={"refresh_token": forjado})

    assert resposta.status_code == 401


async def test_refresh_revogado_deixa_de_funcionar(cliente):
    tokens = await registrar_e_logar(cliente)
    corpo = {"refresh_token": tokens["refresh_token"]}

    assert (await cliente.post("/api/v1/auth/logout", json=corpo)).status_code == 204
    resposta = await cliente.post("/api/v1/auth/refresh", json=corpo)

    assert resposta.status_code == 401


async def test_logout_marca_flag_de_revogacao(cliente, sessao):
    tokens = await registrar_e_logar(cliente)

    await cliente.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})

    registro = await sessao.scalar(select(TokenAtualizacao))
    assert registro.revogado is True


async def test_refresh_expirado_e_recusado(cliente, sessao):
    tokens = await registrar_e_logar(cliente)
    registro = await sessao.scalar(select(TokenAtualizacao))
    registro.expira_em = datetime.now(UTC) - timedelta(seconds=1)
    await sessao.commit()

    resposta = await cliente.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert resposta.status_code == 401


# --------------------------------------------------------------------------- rotas protegidas


async def test_rota_protegida_sem_token_retorna_401(cliente):
    resposta = await cliente.get("/api/v1/auth/eu")

    assert resposta.status_code == 401


async def test_rota_protegida_com_token_valido(cliente):
    tokens = await registrar_e_logar(cliente)

    resposta = await cliente.get(
        "/api/v1/auth/eu", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert resposta.status_code == 200
    assert resposta.json()["email"] == EMAIL


async def test_rota_protegida_recusa_refresh_token_como_bearer(cliente):
    tokens = await registrar_e_logar(cliente)

    resposta = await cliente.get(
        "/api/v1/auth/eu", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )

    assert resposta.status_code == 401


async def test_rota_protegida_recusa_token_adulterado(cliente):
    tokens = await registrar_e_logar(cliente)
    adulterado = tokens["access_token"][:-3] + "aaa"

    resposta = await cliente.get(
        "/api/v1/auth/eu", headers={"Authorization": f"Bearer {adulterado}"}
    )

    assert resposta.status_code == 401


async def test_requer_admin_bloqueia_usuario_pme(cliente):
    tokens = await registrar_e_logar(cliente)

    resposta = await cliente.get(
        ROTA_ADMIN, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert resposta.status_code == 403


async def test_requer_admin_libera_admin(cliente, sessao):
    await registrar(cliente)
    usuario = await sessao.scalar(select(Usuario).where(Usuario.email == EMAIL))
    usuario.papel = "admin"
    await sessao.commit()

    tokens = (await logar(cliente)).json()
    resposta = await cliente.get(
        ROTA_ADMIN, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert resposta.status_code == 200
    assert resposta.json()["papel"] == "admin"


# --------------------------------------------------------------------------- senha em log


@pytest.mark.parametrize("nivel", [logging.DEBUG])
async def test_senha_nunca_aparece_em_log(cliente, caplog, nivel):
    with caplog.at_level(nivel):
        await registrar(cliente)
        await logar(cliente)
        await logar(cliente, senha="SenhaErrada123")

    assert SENHA not in caplog.text
    assert "SenhaErrada123" not in caplog.text


async def test_repr_do_schema_nao_expoe_a_senha():
    from app.schemas.auth import UserRegister

    dados = UserRegister(nome=NOME, email=EMAIL, senha=SENHA)

    assert SENHA not in repr(dados)
    assert SENHA not in str(dados)
    assert dados.senha.get_secret_value() == SENHA
