"""Empresas, convites e membros (ADR-011)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.config import settings
from app.models.convite import Convite
from app.models.empresa import Empresa
from app.models.modelo_analise import ModeloAnalise
from app.models.token_atualizacao import TokenAtualizacao
from app.models.usuario import Usuario
from app.services import empresa as servico_empresa
from app.services.auth import CONVITE_INVALIDO, EMPRESA_LOTADA
from tests.conftest import autenticar, autenticar_convidado, convidar

SENHA = "SenhaForte123"
DONA = "dona@empresa.com"


async def registrar_por_convite(cliente, email: str, token: str):
    return await cliente.post(
        "/api/v1/auth/registrar",
        json={"nome": "Convidada", "email": email, "senha": SENHA, "token_convite": token},
    )


# --------------------------------------------------------------------------- cadastro


async def test_cadastro_cria_empresa_e_dono(cliente, sessao):
    resposta = await cliente.post(
        "/api/v1/auth/registrar",
        json={"nome": "Dona", "email": DONA, "senha": SENHA, "nome_empresa": "  Loja da Dona  "},
    )

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["papel_empresa"] == "dono"
    assert corpo["papel"] == "usuario_pme"
    assert corpo["empresa"]["nome"] == "Loja da Dona"
    assert await sessao.scalar(select(func.count()).select_from(Empresa)) == 1


async def test_cadastro_exige_empresa_ou_convite(cliente):
    sem_nada = await cliente.post(
        "/api/v1/auth/registrar", json={"nome": "X", "email": DONA, "senha": SENHA}
    )
    com_os_dois = await cliente.post(
        "/api/v1/auth/registrar",
        json={
            "nome": "X",
            "email": DONA,
            "senha": SENHA,
            "nome_empresa": "Loja",
            "token_convite": "abc",
        },
    )

    assert sem_nada.status_code == 422
    assert com_os_dois.status_code == 422


async def test_eu_traz_a_empresa(cliente):
    h = await autenticar(cliente, DONA)

    corpo = (await cliente.get("/api/v1/auth/eu", headers=h)).json()

    assert corpo["empresa"]["nome"] == f"Empresa de {DONA}"
    assert corpo["papel_empresa"] == "dono"


# --------------------------------------------------------------------------- convite


async def test_convite_valido_entra_na_empresa_como_membro(cliente, sessao):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "nova@empresa.com")

    resposta = await registrar_por_convite(cliente, "nova@empresa.com", token)

    assert resposta.status_code == 201, resposta.text
    dona = await sessao.scalar(select(Usuario).where(Usuario.email == DONA))
    assert resposta.json()["empresa"]["id_empresa"] == dona.id_empresa
    assert resposta.json()["papel_empresa"] == "membro"
    # Entrar por convite não cria empresa nova.
    assert await sessao.scalar(select(func.count()).select_from(Empresa)) == 1


async def test_convite_pode_ser_de_dono(cliente):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "socia@empresa.com", papel_empresa="dono")

    resposta = await registrar_por_convite(cliente, "socia@empresa.com", token)

    assert resposta.json()["papel_empresa"] == "dono"


async def test_convite_guarda_so_o_hash_do_token(cliente, sessao):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "nova@empresa.com")

    convite = await sessao.scalar(select(Convite))
    assert convite.token_hash != token
    assert len(convite.token_hash) == 64
    # A listagem nunca devolve o link de novo.
    lista = (await cliente.get("/api/v1/empresa/convites", headers=h)).json()
    assert "link" not in lista[0]


async def test_convite_expirado_e_recusado(cliente, sessao):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "nova@empresa.com")
    convite = await sessao.scalar(select(Convite))
    convite.expira_em = datetime.now(UTC) - timedelta(seconds=1)
    await sessao.commit()

    resposta = await registrar_por_convite(cliente, "nova@empresa.com", token)

    assert resposta.status_code == 400
    assert resposta.json()["detail"] == CONVITE_INVALIDO


async def test_convite_ja_usado_e_recusado(cliente):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "nova@empresa.com")
    assert (await registrar_por_convite(cliente, "nova@empresa.com", token)).status_code == 201

    # Mesmo token, outra pessoa tentando reaproveitá-lo com o e-mail certo não dá:
    # o e-mail já tem conta; com outro e-mail, o convite já foi consumido.
    resposta = await registrar_por_convite(cliente, "outra@empresa.com", token)

    assert resposta.status_code == 400
    assert resposta.json()["detail"] == CONVITE_INVALIDO


async def test_convite_com_email_diferente_e_recusado(cliente, sessao):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "nova@empresa.com")

    resposta = await registrar_por_convite(cliente, "intrusa@empresa.com", token)

    assert resposta.status_code == 400
    assert resposta.json()["detail"] == CONVITE_INVALIDO
    # O convite segue valendo para a pessoa certa.
    assert (await sessao.scalar(select(Convite))).usado_em is None


async def test_convite_compara_email_normalizado(cliente):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "Nova@Empresa.com")

    resposta = await registrar_por_convite(cliente, "nova@EMPRESA.com", token)

    assert resposta.status_code == 201


async def test_convite_adulterado_e_recusado(cliente):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "nova@empresa.com")
    adulterado = token[:-2] + ("aa" if not token.endswith("aa") else "bb")

    resposta = await registrar_por_convite(cliente, "nova@empresa.com", adulterado)

    assert resposta.status_code == 400
    assert resposta.json()["detail"] == CONVITE_INVALIDO


async def test_empresa_lotada_recusa_novo_convite(cliente, monkeypatch):
    monkeypatch.setattr(settings, "empresa_max_membros", 3)
    h = await autenticar(cliente, DONA)
    await autenticar_convidado(cliente, h, "m1@empresa.com")
    await convidar(cliente, h, "m2@empresa.com")  # pendente reserva a 3ª vaga

    resposta = await cliente.post(
        "/api/v1/empresa/convites", json={"email": "m3@empresa.com"}, headers=h
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == EMPRESA_LOTADA


async def test_empresa_lotada_recusa_cadastro_por_convite(cliente, sessao, monkeypatch):
    """O limite também vale na entrada: convites antigos não furam o teto se ele baixou."""
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "m1@empresa.com")
    monkeypatch.setattr(settings, "empresa_max_membros", 1)

    resposta = await registrar_por_convite(cliente, "m1@empresa.com", token)

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == EMPRESA_LOTADA
    assert (await sessao.scalar(select(Convite))).usado_em is None


async def test_limite_padrao_e_10_membros():
    assert settings.empresa_max_membros == 10


async def test_convite_responde_igual_para_email_com_e_sem_conta(cliente):
    """Convidar não pode virar consulta de "este e-mail já usa o sistema?"."""
    await autenticar(cliente, "ja-tem-conta@outra.com")
    h = await autenticar(cliente, DONA)

    com_conta = await cliente.post(
        "/api/v1/empresa/convites", json={"email": "ja-tem-conta@outra.com"}, headers=h
    )
    sem_conta = await cliente.post(
        "/api/v1/empresa/convites", json={"email": "ninguem@outra.com"}, headers=h
    )

    assert com_conta.status_code == sem_conta.status_code == 201
    assert set(com_conta.json()) == set(sem_conta.json())


async def test_reconvidar_substitui_o_convite_pendente(cliente, sessao):
    h = await autenticar(cliente, DONA)
    antigo = await convidar(cliente, h, "nova@empresa.com")
    novo = await convidar(cliente, h, "nova@empresa.com")

    assert await sessao.scalar(select(func.count()).select_from(Convite)) == 1
    assert (await registrar_por_convite(cliente, "nova@empresa.com", antigo)).status_code == 400
    assert (await registrar_por_convite(cliente, "nova@empresa.com", novo)).status_code == 201


async def test_revogar_convite(cliente):
    h = await autenticar(cliente, DONA)
    token = await convidar(cliente, h, "nova@empresa.com")
    id_convite = (await cliente.get("/api/v1/empresa/convites", headers=h)).json()[0]["id_convite"]

    resposta = await cliente.delete(f"/api/v1/empresa/convites/{id_convite}", headers=h)

    assert resposta.status_code == 204
    assert (await cliente.get("/api/v1/empresa/convites", headers=h)).json() == []
    assert (await registrar_por_convite(cliente, "nova@empresa.com", token)).status_code == 400


async def test_convite_de_outra_empresa_responde_404(cliente):
    h_a = await autenticar(cliente, DONA)
    h_b = await autenticar(cliente, "dono@outra.com")
    await convidar(cliente, h_a, "nova@empresa.com")
    id_convite = (await cliente.get("/api/v1/empresa/convites", headers=h_a)).json()[0][
        "id_convite"
    ]

    resposta = await cliente.delete(f"/api/v1/empresa/convites/{id_convite}", headers=h_b)

    assert resposta.status_code == 404
    assert len((await cliente.get("/api/v1/empresa/convites", headers=h_a)).json()) == 1


# --------------------------------------------------------------------------- membros


async def test_lista_de_membros(cliente):
    h = await autenticar(cliente, DONA)
    h_membro = await autenticar_convidado(cliente, h, "membro@empresa.com")

    for cabecalho in (h, h_membro):
        membros = (await cliente.get("/api/v1/empresa/membros", headers=cabecalho)).json()
        assert sorted(m["email"] for m in membros) == [DONA, "membro@empresa.com"]
        assert "senha_hash" not in membros[0]


async def test_membros_de_outra_empresa_nao_aparecem(cliente):
    h = await autenticar(cliente, DONA)
    await autenticar(cliente, "dono@outra.com")

    membros = (await cliente.get("/api/v1/empresa/membros", headers=h)).json()

    assert [m["email"] for m in membros] == [DONA]


async def test_membro_nao_consegue_convidar(cliente):
    h = await autenticar(cliente, DONA)
    h_membro = await autenticar_convidado(cliente, h, "membro@empresa.com")

    criar = await cliente.post(
        "/api/v1/empresa/convites", json={"email": "x@empresa.com"}, headers=h_membro
    )
    listar = await cliente.get("/api/v1/empresa/convites", headers=h_membro)

    assert criar.status_code == 403
    assert listar.status_code == 403


async def test_membro_nao_consegue_remover_nem_revogar(cliente, sessao):
    h = await autenticar(cliente, DONA)
    await convidar(cliente, h, "pendente@empresa.com")
    h_membro = await autenticar_convidado(cliente, h, "membro@empresa.com")
    dona = await sessao.scalar(select(Usuario).where(Usuario.email == DONA))
    id_convite = (await sessao.scalar(select(Convite).where(Convite.usado_em.is_(None)))).id_convite

    remover = await cliente.delete(f"/api/v1/empresa/membros/{dona.id_usuario}", headers=h_membro)
    revogar = await cliente.delete(f"/api/v1/empresa/convites/{id_convite}", headers=h_membro)

    assert remover.status_code == 403
    assert revogar.status_code == 403
    assert await sessao.get(Usuario, dona.id_usuario) is not None


async def test_dono_nao_remove_a_si_mesmo(cliente, sessao):
    """Único dono tentando sair: seria deixar a empresa sem dono."""
    h = await autenticar(cliente, DONA)
    dona = await sessao.scalar(select(Usuario).where(Usuario.email == DONA))

    resposta = await cliente.delete(f"/api/v1/empresa/membros/{dona.id_usuario}", headers=h)

    assert resposta.status_code == 409


async def test_nao_remove_o_ultimo_dono(cliente, sessao):
    """A contagem de donos no serviço barra deixar a empresa sem dono.

    Pela API só um dono remove outro, e ele próprio continua — a regra acima já
    cobre esse caminho. Aqui o serviço é chamado direto, com quem remove já sem o
    papel de dono, para provar que a segunda barreira existe e funciona.
    """
    h = await autenticar(cliente, DONA)
    await autenticar_convidado(cliente, h, "socia@empresa.com", papel_empresa="dono")
    dona = await sessao.scalar(select(Usuario).where(Usuario.email == DONA))
    socia = await sessao.scalar(select(Usuario).where(Usuario.email == "socia@empresa.com"))
    dona.papel_empresa = "membro"  # restaria só a sócia como dona
    await sessao.commit()

    with pytest.raises(HTTPException) as erro:
        await servico_empresa.remover_membro(sessao, dona, socia.id_usuario)

    assert erro.value.status_code == 409
    assert erro.value.detail == "A empresa precisa de ao menos um dono."
    assert await sessao.get(Usuario, socia.id_usuario) is not None


async def test_dono_remove_membro_e_herda_os_modelos(cliente, sessao):
    h = await autenticar(cliente, DONA)
    h_membro = await autenticar_convidado(cliente, h, "membro@empresa.com")
    refresh = (
        await cliente.post(
            "/api/v1/auth/login", json={"email": "membro@empresa.com", "senha": SENHA}
        )
    ).json()["refresh_token"]
    criado = await cliente.post(
        "/api/v1/modelos-analise",
        json={"nome": "Do membro", "termo_pesquisa": "", "filtros": {"videos": ["abc"]}},
        headers=h_membro,
    )
    membro = await sessao.scalar(select(Usuario).where(Usuario.email == "membro@empresa.com"))
    dona = await sessao.scalar(select(Usuario).where(Usuario.email == DONA))

    id_membro, id_dona, id_empresa = membro.id_usuario, dona.id_usuario, dona.id_empresa

    resposta = await cliente.delete(f"/api/v1/empresa/membros/{id_membro}", headers=h)

    assert resposta.status_code == 204
    sessao.expire_all()
    assert await sessao.get(Usuario, id_membro) is None
    modelo = await sessao.get(ModeloAnalise, criado.json()["id_modelo"])
    assert modelo.id_usuario == id_dona
    assert modelo.id_empresa == id_empresa
    # A sessão do removido cai na hora: access token e refresh.
    assert (await cliente.get("/api/v1/auth/eu", headers=h_membro)).status_code == 401
    assert (
        await cliente.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    ).status_code == 401
    restantes = await sessao.scalar(
        select(func.count())
        .select_from(TokenAtualizacao)
        .where(TokenAtualizacao.id_usuario == id_membro)
    )
    assert restantes == 0


async def test_remover_membro_de_outra_empresa_responde_404(cliente, sessao):
    h_a = await autenticar(cliente, DONA)
    await autenticar(cliente, "dono@outra.com")
    outro = await sessao.scalar(select(Usuario).where(Usuario.email == "dono@outra.com"))

    resposta = await cliente.delete(f"/api/v1/empresa/membros/{outro.id_usuario}", headers=h_a)

    assert resposta.status_code == 404
    assert await sessao.get(Usuario, outro.id_usuario) is not None


async def test_rotas_da_empresa_exigem_token(cliente):
    assert (await cliente.get("/api/v1/empresa/membros")).status_code == 401
    assert (
        await cliente.post("/api/v1/empresa/convites", json={"email": "x@y.com"})
    ).status_code == 401
