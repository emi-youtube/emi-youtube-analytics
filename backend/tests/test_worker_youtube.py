"""Testes do cliente da YouTube Data API.

Nenhum teste toca a rede: tudo passa por `httpx.MockTransport`. Gastar cota real
num teste é inaceitável — a cota diária é compartilhada pelo projeto inteiro.
"""

import httpx
import pytest

from app.core.security import hash_token
from app.workers.youtube import (
    API_BASE,
    ClienteYouTube,
    ComentariosDesabilitados,
    ErroPermanente,
    ErroTransitorio,
)

CHAVE = "chave-de-teste"
VIDEO_ID = "abc123"
ID_CANAL_AUTOR = "UC_autor_original"
NOME_AUTOR = "Fulano da Silva"


def cliente_com(handler) -> tuple[ClienteYouTube, list[httpx.Request]]:
    """Cliente apontado para um transporte falso, com o registro das requisições."""
    chamadas: list[httpx.Request] = []

    def _registrar(request: httpx.Request) -> httpx.Response:
        chamadas.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(_registrar))
    return ClienteYouTube(CHAVE, http), chamadas


def resposta_comentarios(*, itens: list[dict], proxima_pagina: str | None = None) -> dict:
    corpo: dict = {"items": itens}
    if proxima_pagina:
        corpo["nextPageToken"] = proxima_pagina
    return corpo


def item_comentario(id_comentario: str, *, com_canal: bool = True) -> dict:
    snippet = {
        "textDisplay": f"texto de {id_comentario}",
        "publishedAt": "2026-03-01T12:00:00Z",
        "authorDisplayName": NOME_AUTOR,
    }
    if com_canal:
        snippet["authorChannelId"] = {"value": ID_CANAL_AUTOR}
    return {"snippet": {"topLevelComment": {"id": id_comentario, "snippet": snippet}}}


# --------------------------------------------------------------------------- cota


async def test_search_list_e_recusado_pelo_cliente():
    """CLAUDE.md regra 4: search.list custa 100 unidades contra 1 dos outros."""
    cliente, chamadas = cliente_com(lambda _: httpx.Response(200, json={}))

    with pytest.raises(ErroPermanente, match=r"search\.list"):
        await cliente._get("search", {"q": "tênis"})

    assert chamadas == []


async def test_coleta_completa_usa_so_endpoints_de_1_unidade():
    def handler(request: httpx.Request) -> httpx.Response:
        if "videos" in request.url.path:
            return httpx.Response(200, json={"items": [{"id": VIDEO_ID, "snippet": {}}]})
        return httpx.Response(200, json=resposta_comentarios(itens=[item_comentario("c1")]))

    cliente, chamadas = cliente_com(handler)

    await cliente.listar_videos([VIDEO_ID])
    await cliente.listar_comentarios(VIDEO_ID, limite=100)

    caminhos = [c.url.path.removeprefix("/youtube/v3/") for c in chamadas]
    assert caminhos == ["videos", "commentThreads"]
    assert not any("search" in caminho for caminho in caminhos)


# --------------------------------------------------------------------------- vídeos


async def test_listar_videos_converte_metadados():
    item = {
        "id": VIDEO_ID,
        "snippet": {
            "title": "Campanha de verão",
            "channelTitle": "Loja Exemplo",
            "publishedAt": "2026-02-10T08:30:00Z",
        },
        "statistics": {"viewCount": "15230", "likeCount": "412"},
    }
    cliente, _ = cliente_com(lambda _: httpx.Response(200, json={"items": [item]}))

    videos = await cliente.listar_videos([VIDEO_ID])

    assert len(videos) == 1
    assert videos[0].titulo == "Campanha de verão"
    assert videos[0].canal == "Loja Exemplo"
    assert videos[0].visualizacoes == 15230
    assert videos[0].curtidas == 412
    assert videos[0].publicado_em.year == 2026


async def test_contadores_ocultos_viram_zero():
    """Quem esconde as curtidas faz a API omitir o campo — não pode quebrar a coleta."""
    item = {"id": VIDEO_ID, "snippet": {"title": "t", "channelTitle": "c"}, "statistics": {}}
    cliente, _ = cliente_com(lambda _: httpx.Response(200, json={"items": [item]}))

    videos = await cliente.listar_videos([VIDEO_ID])

    assert videos[0].visualizacoes == 0
    assert videos[0].curtidas == 0


async def test_listar_videos_quebra_em_lotes_de_50():
    cliente, chamadas = cliente_com(lambda _: httpx.Response(200, json={"items": []}))

    await cliente.listar_videos([f"video{n}" for n in range(120)])

    assert len(chamadas) == 3
    assert len(chamadas[0].url.params["id"].split(",")) == 50
    assert len(chamadas[2].url.params["id"].split(",")) == 20


# --------------------------------------------------------------------------- comentários


async def test_autor_nunca_sai_do_cliente_em_texto_plano():
    """LGPD (CLAUDE.md regra 2): só o hash atravessa a fronteira do cliente."""
    cliente, _ = cliente_com(
        lambda _: httpx.Response(200, json=resposta_comentarios(itens=[item_comentario("c1")]))
    )

    comentarios = await cliente.listar_comentarios(VIDEO_ID, limite=10)

    assert comentarios[0].autor_hash == hash_token(ID_CANAL_AUTOR)
    conteudo = repr(comentarios[0])
    assert ID_CANAL_AUTOR not in conteudo
    assert NOME_AUTOR not in conteudo


async def test_autor_sem_canal_usa_o_nome_exibido_tambem_hasheado():
    cliente, _ = cliente_com(
        lambda _: httpx.Response(
            200, json=resposta_comentarios(itens=[item_comentario("c1", com_canal=False)])
        )
    )

    comentarios = await cliente.listar_comentarios(VIDEO_ID, limite=10)

    assert comentarios[0].autor_hash == hash_token(NOME_AUTOR)


async def test_pagina_ate_acabar_o_nextpagetoken():
    paginas = [
        resposta_comentarios(itens=[item_comentario("c1")], proxima_pagina="p2"),
        resposta_comentarios(itens=[item_comentario("c2")]),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        indice = 1 if request.url.params.get("pageToken") == "p2" else 0
        return httpx.Response(200, json=paginas[indice])

    cliente, chamadas = cliente_com(handler)

    comentarios = await cliente.listar_comentarios(VIDEO_ID, limite=100)

    assert [c.youtube_comment_id for c in comentarios] == ["c1", "c2"]
    assert len(chamadas) == 2


async def test_para_de_paginar_ao_atingir_o_limite():
    def handler(_: httpx.Request) -> httpx.Response:
        itens = [item_comentario(f"c{n}") for n in range(100)]
        return httpx.Response(200, json=resposta_comentarios(itens=itens, proxima_pagina="p"))

    cliente, chamadas = cliente_com(handler)

    comentarios = await cliente.listar_comentarios(VIDEO_ID, limite=100)

    assert len(comentarios) == 100
    assert len(chamadas) == 1


# --------------------------------------------------------------------------- erros


@pytest.mark.parametrize("codigo", [429, 500, 502, 503])
async def test_erros_transitorios(codigo):
    cliente, _ = cliente_com(lambda _: httpx.Response(codigo, json={}))

    with pytest.raises(ErroTransitorio):
        await cliente.listar_videos([VIDEO_ID])


async def test_timeout_e_transitorio():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("demorou")

    cliente, _ = cliente_com(handler)

    with pytest.raises(ErroTransitorio):
        await cliente.listar_videos([VIDEO_ID])


@pytest.mark.parametrize("codigo", [400, 403, 404])
async def test_erros_permanentes(codigo):
    cliente, _ = cliente_com(lambda _: httpx.Response(codigo, json={}))

    with pytest.raises(ErroPermanente):
        await cliente.listar_videos([VIDEO_ID])


async def test_comentarios_desabilitados_tem_excecao_propria():
    """403 com reason=commentsDisabled não é falha: o vídeo simplesmente não tem."""
    corpo = {"error": {"errors": [{"reason": "commentsDisabled"}]}}
    cliente, _ = cliente_com(lambda _: httpx.Response(403, json=corpo))

    with pytest.raises(ComentariosDesabilitados):
        await cliente.listar_comentarios(VIDEO_ID, limite=10)


async def test_a_chave_vai_na_query_de_toda_chamada():
    cliente, chamadas = cliente_com(lambda _: httpx.Response(200, json={"items": []}))

    await cliente.listar_videos([VIDEO_ID])

    assert chamadas[0].url.params["key"] == CHAVE
    assert str(chamadas[0].url).startswith(API_BASE)
