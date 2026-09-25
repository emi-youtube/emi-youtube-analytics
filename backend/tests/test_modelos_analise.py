"""Testes do CRUD de modelo de análise (UC02), incluindo isolamento entre usuários."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.execucao import Execucao
from app.models.modelo_analise import ModeloAnalise

from .conftest import autenticar

ROTA = "/api/v1/modelos-analise"

DONO = "dona@exemplo.com"
INTRUSO = "intruso@exemplo.com"


# IDs no formato do YouTube (11 caracteres); o conteúdo não importa aqui.
VIDEO_A = "dQw4w9WgXcQ"
VIDEO_B = "kJQP7kiw5Fk"


async def criar_modelo(cliente: AsyncClient, headers: dict, **campos):
    corpo = {
        "nome": "Campanha de verão",
        "termo_pesquisa": "tênis esportivo",
        # UC02: é o vídeo que dá escopo ao modelo, então todo modelo válido tem um.
        "filtros": {"videos": [VIDEO_A]},
        **campos,
    }
    return await cliente.post(ROTA, json=corpo, headers=headers)


@pytest.fixture
def modelo_valido() -> dict:
    return {
        "nome": "Campanha de verão",
        "termo_pesquisa": "tênis esportivo",
        "filtros": {"videos": [VIDEO_A]},
    }


# --------------------------------------------------------------------------- autenticação


@pytest.mark.parametrize(
    ("metodo", "caminho"),
    [
        ("post", ROTA),
        ("get", ROTA),
        ("get", f"{ROTA}/1"),
        ("patch", f"{ROTA}/1"),
        ("delete", f"{ROTA}/1"),
    ],
)
async def test_todas_as_rotas_exigem_autenticacao(cliente, metodo, caminho):
    resposta = await cliente.request(metodo, caminho, json={})

    assert resposta.status_code == 401


# --------------------------------------------------------------------------- criação


async def test_criar_modelo(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await criar_modelo(cliente, headers)

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["nome"] == "Campanha de verão"
    assert corpo["termo_pesquisa"] == "tênis esportivo"
    assert corpo["id_modelo"]


async def test_criar_modelo_associa_ao_usuario_do_token(cliente, sessao):
    headers = await autenticar(cliente, DONO)

    corpo = (await criar_modelo(cliente, headers)).json()

    modelo = await sessao.scalar(
        select(ModeloAnalise).where(ModeloAnalise.id_modelo == corpo["id_modelo"])
    )
    assert modelo.id_usuario == corpo["id_usuario"]


async def test_criar_sem_nome_retorna_422(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await cliente.post(ROTA, json={"termo_pesquisa": "tênis"}, headers=headers)

    assert resposta.status_code == 422


async def test_criar_com_nome_em_branco_retorna_422(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await criar_modelo(cliente, headers, nome="   ")

    assert resposta.status_code == 422


async def test_criar_persiste_filtros_jsonb(cliente):
    headers = await autenticar(cliente, DONO)
    filtros = {"videos": [VIDEO_A], "canais": ["UCabc123"], "idioma": "pt-BR"}

    corpo = (await criar_modelo(cliente, headers, filtros=filtros)).json()

    # `idioma` não está no schema: a coluna é JSONB e aceita filtros futuros
    assert corpo["filtros"]["canais"] == ["UCabc123"]
    assert corpo["filtros"]["idioma"] == "pt-BR"


# --------------------------------------------------------------- regra de escopo do UC02


async def test_recusa_sem_video(cliente):
    """UC02: sem vídeo a coleta não tem de onde buscar comentário."""
    headers = await autenticar(cliente, DONO)

    resposta = await criar_modelo(cliente, headers, filtros={"videos": []})

    assert resposta.status_code == 422


async def test_recusa_sem_filtros(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await criar_modelo(cliente, headers, filtros=None)

    assert resposta.status_code == 422


async def test_recusa_video_em_branco_como_se_fosse_video(cliente):
    """`videos: ["  "]` não pode driblar a regra."""
    headers = await autenticar(cliente, DONO)

    resposta = await criar_modelo(cliente, headers, filtros={"videos": ["  "]})

    assert resposta.status_code == 422


async def test_recusa_so_com_termo(cliente):
    """Termo sozinho não define escopo: achar vídeo por texto exigiria search.list."""
    headers = await autenticar(cliente, DONO)

    resposta = await criar_modelo(
        cliente, headers, termo_pesquisa="tênis", filtros={"canais": ["UCabc123"]}
    )

    assert resposta.status_code == 422


async def test_aceita_video_sem_termo(cliente):
    """Termo de pesquisa é opcional a partir da Sprint 1."""
    headers = await autenticar(cliente, DONO)

    resposta = await criar_modelo(cliente, headers, termo_pesquisa="")

    assert resposta.status_code == 201
    assert resposta.json()["termo_pesquisa"] == ""


async def test_aceita_video_com_termo(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await criar_modelo(cliente, headers, termo_pesquisa="tênis")

    assert resposta.status_code == 201


# --------------------------------------------------------------------------- listagem


async def test_listar_devolve_apenas_modelos_do_usuario(cliente):
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    await criar_modelo(cliente, headers_dono, nome="Da dona")
    await criar_modelo(cliente, headers_intruso, nome="Do intruso")

    resposta = await cliente.get(ROTA, headers=headers_dono)

    assert resposta.status_code == 200
    nomes = [m["nome"] for m in resposta.json()]
    assert nomes == ["Da dona"]


async def test_listar_vazio_para_usuario_novo(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await cliente.get(ROTA, headers=headers)

    assert resposta.json() == []


# --------------------------------------------------------------------------- detalhe


async def test_detalhar_modelo_proprio(cliente):
    headers = await autenticar(cliente, DONO)
    id_modelo = (await criar_modelo(cliente, headers)).json()["id_modelo"]

    resposta = await cliente.get(f"{ROTA}/{id_modelo}", headers=headers)

    assert resposta.status_code == 200
    assert resposta.json()["id_modelo"] == id_modelo


async def test_detalhar_modelo_inexistente_retorna_404(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await cliente.get(f"{ROTA}/99999", headers=headers)

    assert resposta.status_code == 404


async def test_detalhar_modelo_de_outro_usuario_retorna_404(cliente):
    """404 e não 403: um 403 confirmaria que aquele id existe."""
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    id_modelo = (await criar_modelo(cliente, headers_dono)).json()["id_modelo"]

    resposta = await cliente.get(f"{ROTA}/{id_modelo}", headers=headers_intruso)

    assert resposta.status_code == 404


async def test_resposta_de_modelo_alheio_e_de_inexistente_sao_iguais(cliente):
    """Qualquer diferença entre as duas respostas vira oráculo de existência."""
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    id_existente = (await criar_modelo(cliente, headers_dono)).json()["id_modelo"]

    alheio = await cliente.get(f"{ROTA}/{id_existente}", headers=headers_intruso)
    inexistente = await cliente.get(f"{ROTA}/99999", headers=headers_intruso)

    assert alheio.status_code == inexistente.status_code
    assert alheio.json() == inexistente.json()


# --------------------------------------------------------------------------- atualização


async def test_atualizar_modelo_proprio(cliente):
    headers = await autenticar(cliente, DONO)
    id_modelo = (await criar_modelo(cliente, headers)).json()["id_modelo"]

    resposta = await cliente.patch(
        f"{ROTA}/{id_modelo}", json={"nome": "Nome novo"}, headers=headers
    )

    assert resposta.status_code == 200
    assert resposta.json()["nome"] == "Nome novo"


async def test_patch_parcial_preserva_os_demais_campos(cliente):
    headers = await autenticar(cliente, DONO)
    criado = (
        await criar_modelo(cliente, headers, filtros={"videos": [VIDEO_A], "canais": ["UCabc123"]})
    ).json()

    atualizado = (
        await cliente.patch(
            f"{ROTA}/{criado['id_modelo']}", json={"nome": "Só o nome"}, headers=headers
        )
    ).json()

    assert atualizado["nome"] == "Só o nome"
    assert atualizado["termo_pesquisa"] == criado["termo_pesquisa"]
    assert atualizado["filtros"] == criado["filtros"]


async def test_patch_nao_pode_deixar_o_modelo_sem_video(cliente):
    """A regra do UC02 vale no PATCH, senão dava para contorná-la em dois passos."""
    headers = await autenticar(cliente, DONO)
    id_modelo = (await criar_modelo(cliente, headers)).json()["id_modelo"]

    resposta = await cliente.patch(
        f"{ROTA}/{id_modelo}", json={"filtros": {"videos": []}}, headers=headers
    )

    assert resposta.status_code == 422


async def test_patch_aceita_esvaziar_o_termo(cliente):
    """O termo é opcional: esvaziá-lo não mexe no escopo, que vem dos vídeos."""
    headers = await autenticar(cliente, DONO)
    id_modelo = (await criar_modelo(cliente, headers)).json()["id_modelo"]

    resposta = await cliente.patch(
        f"{ROTA}/{id_modelo}", json={"termo_pesquisa": ""}, headers=headers
    )

    assert resposta.status_code == 200
    assert resposta.json()["termo_pesquisa"] == ""


async def test_patch_ignora_troca_de_dono(cliente, sessao):
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    criado = (await criar_modelo(cliente, headers_dono)).json()
    eu_intruso = await cliente.get("/api/v1/auth/eu", headers=headers_intruso)
    id_intruso = eu_intruso.json()["id_usuario"]

    await cliente.patch(
        f"{ROTA}/{criado['id_modelo']}",
        json={"nome": "Novo", "id_usuario": id_intruso},
        headers=headers_dono,
    )

    modelo = await sessao.scalar(
        select(ModeloAnalise).where(ModeloAnalise.id_modelo == criado["id_modelo"])
    )
    assert modelo.id_usuario == criado["id_usuario"]


async def test_atualizar_modelo_de_outro_usuario_retorna_404(cliente, sessao):
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    id_modelo = (await criar_modelo(cliente, headers_dono)).json()["id_modelo"]

    resposta = await cliente.patch(
        f"{ROTA}/{id_modelo}", json={"nome": "Invadido"}, headers=headers_intruso
    )

    assert resposta.status_code == 404
    modelo = await sessao.scalar(select(ModeloAnalise).where(ModeloAnalise.id_modelo == id_modelo))
    assert modelo.nome == "Campanha de verão"


# --------------------------------------------------------------------------- remoção


async def test_remover_modelo_proprio(cliente):
    headers = await autenticar(cliente, DONO)
    id_modelo = (await criar_modelo(cliente, headers)).json()["id_modelo"]

    resposta = await cliente.delete(f"{ROTA}/{id_modelo}", headers=headers)

    assert resposta.status_code == 204
    assert (await cliente.get(f"{ROTA}/{id_modelo}", headers=headers)).status_code == 404


async def test_remover_modelo_inexistente_retorna_404(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await cliente.delete(f"{ROTA}/99999", headers=headers)

    assert resposta.status_code == 404


async def test_remover_modelo_de_outro_usuario_nao_apaga_nada(cliente):
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    id_modelo = (await criar_modelo(cliente, headers_dono)).json()["id_modelo"]

    resposta = await cliente.delete(f"{ROTA}/{id_modelo}", headers=headers_intruso)

    assert resposta.status_code == 404
    # o dono continua enxergando o modelo
    assert (await cliente.get(f"{ROTA}/{id_modelo}", headers=headers_dono)).status_code == 200


async def test_remover_modelo_com_execucao_retorna_409(cliente, sessao):
    """EXECUCOES referencia MODELOS_ANALISE sem cascade — apagar levaria o histórico junto."""
    headers = await autenticar(cliente, DONO)
    id_modelo = (await criar_modelo(cliente, headers)).json()["id_modelo"]
    sessao.add(Execucao(id_modelo=id_modelo, status="concluida"))
    await sessao.commit()

    resposta = await cliente.delete(f"{ROTA}/{id_modelo}", headers=headers)

    assert resposta.status_code == 409
    assert (await cliente.get(f"{ROTA}/{id_modelo}", headers=headers)).status_code == 200
