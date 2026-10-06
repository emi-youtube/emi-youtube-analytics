"""Privilégios do dono (ADR-013): quem altera modelo, promover/rebaixar e saída do dono."""

import logging

from sqlalchemy import func, select

from app.core.config import settings
from app.models.empresa import Empresa
from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario
from app.services import permissao
from app.services.conta import DONO_COM_MEMBROS
from app.services.empresa import ULTIMO_DONO
from tests.conftest import autenticar, autenticar_convidado, convidar

SENHA = "SenhaForte123"
DONA = "dona@loja.com"
ANA = "ana@loja.com"
BIA = "bia@loja.com"
OUTRA = "dona@concorrente.com"

MODELO = {"nome": "Campanha da Ana", "filtros": {"videos": ["v1"]}}


async def criar_modelo(cliente, cabecalho, nome: str = "Campanha da Ana") -> int:
    resposta = await cliente.post(
        "/api/v1/modelos-analise", json={**MODELO, "nome": nome}, headers=cabecalho
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id_modelo"]


async def id_de(sessao, email: str) -> int:
    sessao.expire_all()
    return await sessao.scalar(select(Usuario.id_usuario).where(Usuario.email == email))


async def equipe(cliente):
    """Dona + membros Ana e Bia na mesma empresa; Ana cria um modelo."""
    dona = await autenticar(cliente, DONA)
    ana = await autenticar_convidado(cliente, dona, ANA)
    bia = await autenticar_convidado(cliente, dona, BIA)
    id_modelo = await criar_modelo(cliente, ana)
    return dona, ana, bia, id_modelo


async def alterar_papel(cliente, cabecalho, id_usuario: int, papel: str):
    return await cliente.patch(
        f"/api/v1/empresa/membros/{id_usuario}",
        json={"papel_empresa": papel},
        headers=cabecalho,
    )


async def excluir_conta(cliente, cabecalho):
    return await cliente.request(
        "DELETE", "/api/v1/conta", json={"senha": SENHA}, headers=cabecalho
    )


# --------------------------------------------------------------------------- regra 1


async def _agir(cliente, cabecalho, id_modelo: int) -> tuple[int, int]:
    """(status do PATCH, status do DELETE) de `cabecalho` sobre o modelo."""
    editar = await cliente.patch(
        f"/api/v1/modelos-analise/{id_modelo}", json={"nome": "Outro nome"}, headers=cabecalho
    )
    apagar = await cliente.delete(f"/api/v1/modelos-analise/{id_modelo}", headers=cabecalho)
    return editar.status_code, apagar.status_code


async def test_membro_nao_altera_modelo_de_colega(cliente, sessao):
    _, _, bia, id_modelo = await equipe(cliente)

    assert await _agir(cliente, bia, id_modelo) == (403, 403)
    resposta = await cliente.patch(
        f"/api/v1/modelos-analise/{id_modelo}", json={"nome": "x"}, headers=bia
    )
    assert resposta.json()["detail"] == permissao.SO_AUTOR_OU_DONO
    sessao.expire_all()
    modelo = await sessao.get(ModeloAnalise, id_modelo)
    assert modelo.nome == "Campanha da Ana"


async def test_autor_altera_o_proprio_modelo(cliente):
    _, ana, _, id_modelo = await equipe(cliente)

    assert await _agir(cliente, ana, id_modelo) == (200, 204)


async def test_dono_altera_modelo_de_qualquer_membro(cliente):
    dona, _, _, id_modelo = await equipe(cliente)

    assert await _agir(cliente, dona, id_modelo) == (200, 204)


async def test_outra_empresa_continua_404_e_nao_403(cliente):
    _, _, _, id_modelo = await equipe(cliente)
    outra = await autenticar(cliente, OUTRA)

    assert await _agir(cliente, outra, id_modelo) == (404, 404)


async def test_membro_ainda_le_e_executa_modelo_de_colega(cliente):
    _, _, bia, id_modelo = await equipe(cliente)

    assert (
        await cliente.get(f"/api/v1/modelos-analise/{id_modelo}", headers=bia)
    ).status_code == 200
    execucao = await cliente.post("/api/v1/execucoes", json={"id_modelo": id_modelo}, headers=bia)
    assert execucao.status_code == 202, execucao.text


async def test_lista_traz_autor_por_nome_e_quem_pode_alterar(cliente):
    dona, ana, bia, _ = await equipe(cliente)

    def por_pessoa(resposta):
        (modelo,) = resposta.json()
        return modelo["autor_nome"], modelo["pode_alterar"]

    lista = "/api/v1/modelos-analise"
    assert por_pessoa(await cliente.get(lista, headers=ana)) == (f"Conta {ANA}", True)
    assert por_pessoa(await cliente.get(lista, headers=dona)) == (f"Conta {ANA}", True)
    assert por_pessoa(await cliente.get(lista, headers=bia)) == (f"Conta {ANA}", False)
    # Nome, nunca o e-mail do colega.
    assert ANA not in (await cliente.get(lista, headers=bia)).text.replace(f"Conta {ANA}", "")


async def test_modelo_executado_continua_409_para_o_autor(cliente):
    _, ana, _, id_modelo = await equipe(cliente)
    await cliente.post("/api/v1/execucoes", json={"id_modelo": id_modelo}, headers=ana)

    apagar = await cliente.delete(f"/api/v1/modelos-analise/{id_modelo}", headers=ana)

    assert apagar.status_code == 409


async def test_mutacao_sem_checagem_de_autoria_os_testes_pegam(cliente, sessao, monkeypatch):
    """Troca a checagem por "sempre pode" e confere que o cenário do 403 deixa de dar
    403: prova que `test_membro_nao_altera_modelo_de_colega` depende da checagem, e
    não passa por acaso (por exemplo, por um 403 vindo de outro lugar)."""
    _, _, bia, id_modelo = await equipe(cliente)
    monkeypatch.setattr(permissao, "pode_alterar_modelo", lambda usuario, modelo: True)

    assert await _agir(cliente, bia, id_modelo) == (200, 204)


# --------------------------------------------------------------------------- regra 2


async def test_dono_promove_e_rebaixa_membro(cliente, sessao, caplog):
    dona, _, _, _ = await equipe(cliente)
    id_ana = await id_de(sessao, ANA)

    with caplog.at_level(logging.INFO, logger="app.services.empresa"):
        promovida = await alterar_papel(cliente, dona, id_ana, "dono")
    assert promovida.status_code == 200
    assert promovida.json()["papel_empresa"] == "dono"
    assert "evento=papel_alterado" in caplog.text
    assert f"alvo={id_ana} de=membro para=dono" in caplog.text

    rebaixada = await alterar_papel(cliente, dona, id_ana, "membro")
    assert rebaixada.json()["papel_empresa"] == "membro"


async def test_ultimo_dono_nao_pode_ser_rebaixado(cliente, sessao):
    dona, _, _, _ = await equipe(cliente)

    resposta = await alterar_papel(cliente, dona, await id_de(sessao, DONA), "membro")

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == ULTIMO_DONO


async def test_dono_pode_rebaixar_a_si_mesmo_se_sobrar_outro(cliente, sessao):
    dona, _, _, _ = await equipe(cliente)
    await alterar_papel(cliente, dona, await id_de(sessao, ANA), "dono")

    resposta = await alterar_papel(cliente, dona, await id_de(sessao, DONA), "membro")

    assert resposta.status_code == 200
    assert resposta.json()["papel_empresa"] == "membro"


async def test_limite_de_donos(cliente, sessao, monkeypatch):
    monkeypatch.setattr(settings, "empresa_max_donos", 2)
    dona, _, _, _ = await equipe(cliente)
    assert (await alterar_papel(cliente, dona, await id_de(sessao, ANA), "dono")).status_code == 200

    resposta = await alterar_papel(cliente, dona, await id_de(sessao, BIA), "dono")

    assert resposta.status_code == 409
    assert "máximo de 2 donos" in resposta.json()["detail"]


async def test_limite_padrao_e_3_donos():
    assert settings.empresa_max_donos == 3


async def test_convite_de_dono_conta_no_limite(cliente, sessao, monkeypatch):
    monkeypatch.setattr(settings, "empresa_max_donos", 2)
    dona, _, _, _ = await equipe(cliente)
    # Convite de dono continua permitido para o dono...
    await convidar(cliente, dona, "nova-dona@loja.com", papel_empresa="dono")

    # ...e reserva a vaga: com ele pendente, não dá para promover mais ninguém.
    resposta = await alterar_papel(cliente, dona, await id_de(sessao, ANA), "dono")
    assert resposta.status_code == 409
    segundo = await cliente.post(
        "/api/v1/empresa/convites",
        json={"email": "outra-dona@loja.com", "papel_empresa": "dono"},
        headers=dona,
    )
    assert segundo.status_code == 409


async def test_convite_de_dono_aceito_entra_como_dono(cliente):
    dona = await autenticar(cliente, DONA)
    nova = await autenticar_convidado(cliente, dona, "nova-dona@loja.com", papel_empresa="dono")

    eu = await cliente.get("/api/v1/auth/eu", headers=nova)

    assert eu.json()["papel_empresa"] == "dono"


async def test_alvo_de_outra_empresa_responde_404(cliente, sessao):
    dona, _, _, _ = await equipe(cliente)
    await autenticar(cliente, OUTRA)

    resposta = await alterar_papel(cliente, dona, await id_de(sessao, OUTRA), "dono")

    assert resposta.status_code == 404


async def test_membro_nao_promove(cliente, sessao):
    _, ana, _, _ = await equipe(cliente)

    resposta = await alterar_papel(cliente, ana, await id_de(sessao, ANA), "dono")

    assert resposta.status_code == 403
    sessao.expire_all()
    papel = await sessao.scalar(select(Usuario.papel_empresa).where(Usuario.email == ANA))
    assert papel == "membro"


async def test_rebaixado_perde_o_poder_na_hora_com_o_mesmo_token(cliente, sessao):
    dona, ana, _, _ = await equipe(cliente)
    id_ana = await id_de(sessao, ANA)
    await alterar_papel(cliente, dona, id_ana, "dono")
    # Com o token emitido ANTES de qualquer mudança, Ana já age como dona...
    assert (await cliente.get("/api/v1/empresa/convites", headers=ana)).status_code == 200

    await alterar_papel(cliente, dona, id_ana, "membro")

    # ...e o mesmo token deixa de valer para rotas de dono na requisição seguinte.
    assert (await cliente.get("/api/v1/empresa/convites", headers=ana)).status_code == 403


# --------------------------------------------------------------------------- regra 3


async def test_dono_unico_com_membros_nao_sai_ate_promover_outro(cliente, sessao):
    dona, _, _, _ = await equipe(cliente)
    id_dona = await id_de(sessao, DONA)
    id_modelo_da_dona = await criar_modelo(cliente, dona, "Campanha da Dona")

    recusa = await excluir_conta(cliente, dona)
    assert recusa.status_code == 409
    assert recusa.json()["detail"] == DONO_COM_MEMBROS
    assert await id_de(sessao, DONA) == id_dona

    id_ana = await id_de(sessao, ANA)
    await alterar_papel(cliente, dona, id_ana, "dono")
    saida = await excluir_conta(cliente, dona)

    assert saida.status_code == 204, saida.text
    assert await id_de(sessao, DONA) is None
    sessao.expire_all()
    assert await sessao.scalar(select(func.count()).select_from(Empresa)) == 1
    modelo = await sessao.get(ModeloAnalise, id_modelo_da_dona)
    assert modelo.id_usuario == id_ana  # foi para o outro dono


async def test_dono_que_sai_transfere_ao_dono_mais_antigo(cliente, sessao):
    dona, _, _, _ = await equipe(cliente)
    await alterar_papel(cliente, dona, await id_de(sessao, BIA), "dono")
    await alterar_papel(cliente, dona, await id_de(sessao, ANA), "dono")
    id_modelo = await criar_modelo(cliente, dona, "Campanha da Dona")

    assert (await excluir_conta(cliente, dona)).status_code == 204

    sessao.expire_all()
    modelo = await sessao.get(ModeloAnalise, id_modelo)
    # Ana entrou antes de Bia (cadastro), embora tenha sido promovida depois.
    assert modelo.id_usuario == await id_de(sessao, ANA)


async def test_dono_que_sai_perde_os_refresh_tokens(cliente, sessao):
    dona, _, _, _ = await equipe(cliente)
    await alterar_papel(cliente, dona, await id_de(sessao, ANA), "dono")
    login = await cliente.post("/api/v1/auth/login", json={"email": DONA, "senha": SENHA})
    refresh = login.json()["refresh_token"]

    assert (await excluir_conta(cliente, dona)).status_code == 204

    resposta = await cliente.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resposta.status_code == 401
