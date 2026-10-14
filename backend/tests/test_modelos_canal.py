"""Conferência de canal no salvamento do modelo (III.E.2, services/canal.py).

A YouTube API é o cliente real sobre um `httpx.MockTransport`: nenhum teste toca a
rede, e o orçamento de cota e a contagem de unidades são os de produção.
"""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.models.modelo_analise import ModeloAnalise
from app.services import canal, cota
from app.workers.youtube import ClienteYouTube, VideoColetado

from .conftest import autenticar

ROTA = "/api/v1/modelos-analise"

# IDs no formato do YouTube (11 caracteres).
APPLE_1 = "aaaaaaaaaa1"
APPLE_2 = "aaaaaaaaaa2"
APPLE_3 = "aaaaaaaaaa3"
OUTRO_1 = "bbbbbbbbbb1"

CANAIS = {
    APPLE_1: ("UC_apple", "Apple"),
    APPLE_2: ("UC_apple", "Apple"),
    APPLE_3: ("UC_apple", "Apple"),
    OUTRO_1: ("UC_outro", "Outra Marca"),
}


def _item(video_id: str) -> dict:
    id_canal, nome = CANAIS[video_id]
    return {
        "id": video_id,
        "snippet": {
            "title": f"Vídeo {video_id}",
            "channelTitle": nome,
            "channelId": id_canal,
            "publishedAt": "2026-09-01T12:00:00Z",
        },
        "statistics": {"viewCount": "1000", "likeCount": "10"},
    }


class YouTubeFalso:
    """Responde `videos.list` com os canais de `CANAIS` e guarda as chamadas."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.chamadas: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.chamadas.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"errors": [{"reason": "x"}]}})
        ids = request.url.params["id"].split(",")
        return httpx.Response(200, json={"items": [_item(i) for i in ids if i in CANAIS]})


@pytest.fixture
def youtube(cliente):
    """Troca o `None` do conftest por um cliente sobre o transporte falso."""
    falso = YouTubeFalso()

    async def _cliente_falso():
        async with httpx.AsyncClient(transport=httpx.MockTransport(falso)) as http:
            yield ClienteYouTube("chave", http)

    app.dependency_overrides[canal.get_cliente_youtube] = _cliente_falso
    return falso


def _corpo(*videos: str, nome: str = "Campanha") -> dict:
    return {"nome": nome, "termo_pesquisa": "", "filtros": {"videos": list(videos)}}


async def _modelos(sessao) -> list[ModeloAnalise]:
    return list((await sessao.scalars(select(ModeloAnalise))).all())


async def test_videos_do_mesmo_canal_salvam_e_custam_uma_unidade(cliente, youtube, sessao):
    headers = await autenticar(cliente, "dona@exemplo.com")

    resposta = await cliente.post(ROTA, json=_corpo(APPLE_1, APPLE_2), headers=headers)

    assert resposta.status_code == 201, resposta.text
    assert len(youtube.chamadas) == 1
    assert youtube.chamadas[0].url.path.endswith("/videos")
    assert await cota.usado_hoje(sessao, datetime.now(UTC)) == 1


async def test_canais_diferentes_sao_recusados_embaixo_do_campo(cliente, youtube, sessao):
    headers = await autenticar(cliente, "dona@exemplo.com")

    resposta = await cliente.post(ROTA, json=_corpo(APPLE_1, OUTRO_1, APPLE_2), headers=headers)

    assert resposta.status_code == 422
    [erro] = resposta.json()["detail"]
    assert erro["loc"] == ["body", "filtros", "videos"]
    assert erro["type"] == "canais_diferentes"
    # O canal com mais vídeos vem primeiro, e cada um mostra os próprios IDs.
    assert "2 canais diferentes: Apple (2 vídeos: aaaaaaaaaa1, aaaaaaaaaa2)" in erro["msg"]
    assert "Outra Marca (1 vídeo: bbbbbbbbbb1)" in erro["msg"]
    assert await _modelos(sessao) == []
    # A chamada chegou à API, então conta na cota mesmo com o modelo recusado.
    assert await cota.usado_hoje(sessao, datetime.now(UTC)) == 1


async def test_um_video_so_nao_gasta_cota(cliente, youtube):
    headers = await autenticar(cliente, "dona@exemplo.com")

    resposta = await cliente.post(ROTA, json=_corpo(APPLE_1), headers=headers)

    assert resposta.status_code == 201
    assert youtube.chamadas == []


async def test_falha_da_api_nao_impede_o_salvamento(cliente, youtube, sessao):
    # A regra continua valendo na coleta; aqui a conferência é só uma ajuda.
    youtube.status = 500
    headers = await autenticar(cliente, "dona@exemplo.com")

    resposta = await cliente.post(ROTA, json=_corpo(APPLE_1, OUTRO_1), headers=headers)

    assert resposta.status_code == 201
    assert len(await _modelos(sessao)) == 1


async def test_sem_cota_nao_chama_a_api_e_salva(cliente, youtube, sessao):
    await cota.marcar_esgotada(sessao, datetime.now(UTC))
    headers = await autenticar(cliente, "dona@exemplo.com")

    resposta = await cliente.post(ROTA, json=_corpo(APPLE_1, OUTRO_1), headers=headers)

    assert resposta.status_code == 201
    assert youtube.chamadas == []


async def test_editar_so_o_nome_nao_chama_a_api(cliente, youtube):
    headers = await autenticar(cliente, "dona@exemplo.com")
    criado = await cliente.post(ROTA, json=_corpo(APPLE_1, APPLE_2), headers=headers)
    youtube.chamadas.clear()

    resposta = await cliente.patch(
        f"{ROTA}/{criado.json()['id_modelo']}", json={"nome": "Outro nome"}, headers=headers
    )

    assert resposta.status_code == 200
    assert youtube.chamadas == []


async def test_editar_para_canais_diferentes_e_recusado_e_nada_muda(cliente, youtube, sessao):
    headers = await autenticar(cliente, "dona@exemplo.com")
    criado = await cliente.post(ROTA, json=_corpo(APPLE_1, APPLE_2), headers=headers)

    resposta = await cliente.patch(
        f"{ROTA}/{criado.json()['id_modelo']}",
        json={"filtros": {"videos": [APPLE_1, OUTRO_1]}},
        headers=headers,
    )

    assert resposta.status_code == 422
    assert resposta.json()["detail"][0]["type"] == "canais_diferentes"
    [modelo] = await _modelos(sessao)
    await sessao.refresh(modelo)
    assert modelo.filtros["videos"] == [APPLE_1, APPLE_2]


def _video(video_id: str, canal_nome: str) -> VideoColetado:
    return VideoColetado(
        youtube_video_id=video_id,
        titulo="",
        canal=canal_nome,
        publicado_em=None,
        visualizacoes=0,
        curtidas=0,
        id_canal=canal_nome,
    )


def test_mensagem_resume_canal_com_muitos_videos():
    por_canal = {
        "A": [_video(f"a{i}", "Canal A") for i in range(5)],
        "B": [_video("b0", "Canal B")],
        "C": [_video("c0", "Canal C")],
    }

    mensagem = canal.mensagem_canais_diferentes(por_canal)

    assert mensagem.startswith(
        "Os vídeos são de 3 canais diferentes: Canal A (5 vídeos: a0, a1, a2 e mais 2), "
        "Canal B (1 vídeo: b0) e Canal C (1 vídeo: c0)."
    )
