"""Isolamento por EMPRESA (ADR-011): o que é de A nunca aparece para B, e vice-versa.

Três partes:

1. Toda rota que lê ou altera modelo/execução/resultado/relatório responde 404 para
   a outra empresa, e nenhuma listagem traz recurso alheio.
2. Dois usuários da MESMA empresa enxergam os mesmos recursos.
3. **Teste de mutação.** O filtro de posse mora num lugar só
   (`app.services.escopo.da_empresa`). O último teste o troca por "sem filtro" e
   confere que a verificação da parte 1 acusa vazamento em CADA rota. Sem isso, a
   parte 1 poderia passar por acaso — por exemplo, se o id consultado nem existisse
   — e não provaria nada.

O relatório exportável do UC06 é uma página do frontend que consome
`GET /execucoes/{id}/resultado`: protegê-la é proteger essa rota.
"""

from sqlalchemy import select, true

from app.models.usuario import Usuario
from app.services import escopo
from tests.conftest import autenticar_convidado
from tests.test_resultados import montar_cenario


async def _cenario_duas_empresas(cliente, sessao) -> tuple[dict, dict]:
    a = await montar_cenario(cliente, sessao, email="a@empresa-a.com", nome_modelo="Modelo A")
    b = await montar_cenario(cliente, sessao, email="b@empresa-b.com", nome_modelo="Modelo B")
    assert a["usuario"].id_empresa != b["usuario"].id_empresa
    return a, b


async def _vazamentos(cliente, quem: dict, alvo: dict) -> list[str]:
    """Rotas em que `quem` alcança um recurso da empresa de `alvo`. Vazio = isolado."""
    h = quem["cabecalho"]
    id_modelo = alvo["modelo"].id_modelo
    id_execucao = alvo["execucao"].id_execucao
    vazou: list[str] = []

    # --- por id: tem de ser 404, como um id que não existe ---
    por_id = {
        "GET /modelos-analise/{id}": cliente.get(f"/api/v1/modelos-analise/{id_modelo}", headers=h),
        "PATCH /modelos-analise/{id}": cliente.patch(
            f"/api/v1/modelos-analise/{id_modelo}", json={"nome": "invadido"}, headers=h
        ),
        "DELETE /modelos-analise/{id}": cliente.delete(
            f"/api/v1/modelos-analise/{id_modelo}", headers=h
        ),
        "POST /execucoes (modelo alheio)": cliente.post(
            "/api/v1/execucoes", json={"id_modelo": id_modelo}, headers=h
        ),
        "GET /execucoes/{id}": cliente.get(f"/api/v1/execucoes/{id_execucao}", headers=h),
        "GET /execucoes/{id}/resultado (e relatorio)": cliente.get(
            f"/api/v1/execucoes/{id_execucao}/resultado", headers=h
        ),
        "GET /execucoes/{id}/comentarios": cliente.get(
            f"/api/v1/execucoes/{id_execucao}/comentarios", headers=h
        ),
    }
    for rota, chamada in por_id.items():
        resposta = await chamada
        if resposta.status_code != 404:
            vazou.append(f"{rota} -> {resposta.status_code}")

    # --- listagens: o recurso alheio não pode aparecer ---
    modelos = (await cliente.get("/api/v1/modelos-analise", headers=h)).json()
    if any(m["id_modelo"] == id_modelo for m in modelos):
        vazou.append("GET /modelos-analise")

    execucoes = (await cliente.get("/api/v1/execucoes", headers=h)).json()
    if any(e["id_execucao"] == id_execucao for e in execucoes):
        vazou.append("GET /execucoes")

    resultados = (await cliente.get("/api/v1/execucoes/resultados", headers=h)).json()
    if any(r["id_execucao"] == id_execucao for r in resultados):
        vazou.append("GET /execucoes/resultados")

    painel = (await cliente.get("/api/v1/painel", headers=h)).json()
    if any(m["id_modelo"] == id_modelo for m in painel["modelos"]):
        vazou.append("GET /painel")

    return vazou


ROTAS_VERIFICADAS = 11


async def test_empresa_a_nao_alcanca_nada_da_empresa_b(cliente, sessao):
    a, b = await _cenario_duas_empresas(cliente, sessao)

    assert await _vazamentos(cliente, a, b) == []


async def test_empresa_b_nao_alcanca_nada_da_empresa_a(cliente, sessao):
    a, b = await _cenario_duas_empresas(cliente, sessao)

    assert await _vazamentos(cliente, b, a) == []


async def test_recurso_de_outra_empresa_continua_intacto(cliente, sessao):
    """PATCH e DELETE recusados não podem ter alterado nada antes de recusar."""
    a, b = await _cenario_duas_empresas(cliente, sessao)
    await _vazamentos(cliente, a, b)

    resposta = await cliente.get(
        f"/api/v1/modelos-analise/{b['modelo'].id_modelo}", headers=b["cabecalho"]
    )
    assert resposta.status_code == 200
    assert resposta.json()["nome"] == "Modelo B"


# --------------------------------------------------------------------------- mesma empresa


async def test_dois_usuarios_da_mesma_empresa_veem_os_mesmos_recursos(cliente, sessao):
    a = await montar_cenario(cliente, sessao, email="dona@empresa-a.com")
    colega = {
        "cabecalho": await autenticar_convidado(cliente, a["cabecalho"], "colega@empresa-a.com")
    }
    id_modelo = a["modelo"].id_modelo
    id_execucao = a["execucao"].id_execucao
    h = colega["cabecalho"]

    for url in (
        f"/api/v1/modelos-analise/{id_modelo}",
        f"/api/v1/execucoes/{id_execucao}",
        f"/api/v1/execucoes/{id_execucao}/resultado",
        f"/api/v1/execucoes/{id_execucao}/comentarios",
    ):
        assert (await cliente.get(url, headers=h)).status_code == 200, url

    assert [
        m["id_modelo"] for m in (await cliente.get("/api/v1/modelos-analise", headers=h)).json()
    ] == [id_modelo]
    assert [
        r["id_execucao"]
        for r in (await cliente.get("/api/v1/execucoes/resultados", headers=h)).json()
    ] == [id_execucao]
    painel = (await cliente.get("/api/v1/painel", headers=h)).json()
    assert [m["id_modelo"] for m in painel["modelos"]] == [id_modelo]


async def test_modelo_criado_por_membro_aparece_para_o_dono(cliente, sessao):
    a = await montar_cenario(cliente, sessao, email="dona@empresa-a.com")
    h_colega = await autenticar_convidado(cliente, a["cabecalho"], "colega@empresa-a.com")

    criado = await cliente.post(
        "/api/v1/modelos-analise",
        json={"nome": "Do colega", "termo_pesquisa": "", "filtros": {"videos": ["abc"]}},
        headers=h_colega,
    )
    assert criado.status_code == 201, criado.text
    colega = await sessao.scalar(select(Usuario).where(Usuario.email == "colega@empresa-a.com"))
    # Autor é quem criou; dono do recurso é a empresa.
    assert criado.json()["id_usuario"] == colega.id_usuario
    assert criado.json()["id_empresa"] == a["usuario"].id_empresa

    resposta = await cliente.get(
        f"/api/v1/modelos-analise/{criado.json()['id_modelo']}", headers=a["cabecalho"]
    )
    assert resposta.status_code == 200


# --------------------------------------------------------------------------- mutação


async def test_mutacao_sem_filtro_de_empresa_os_testes_pegam_o_vazamento(
    cliente, sessao, monkeypatch
):
    """Troca o filtro de posse por "sem filtro" e exige que CADA rota vaze.

    Se alguma rota continuasse respondendo 404 sem o filtro, a proteção dela não
    viria do filtro — e o teste de isolamento não estaria provando o que diz.
    """
    a, b = await _cenario_duas_empresas(cliente, sessao)
    monkeypatch.setattr(escopo, "da_empresa", lambda usuario: true())

    vazou = await _vazamentos(cliente, a, b)

    assert len(vazou) == ROTAS_VERIFICADAS, vazou
