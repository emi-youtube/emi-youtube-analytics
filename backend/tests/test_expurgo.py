"""Expurgo dos dados do YouTube (ADR-015, `app/workers/expurgo.py`).

As políticas dos YouTube API Services não deixam guardar o texto dos comentários por
mais de 30 dias. O que estes testes defendem é a fronteira: o que vem da API sai no
prazo, e o que o Emi calculou (sentimento, temas, percentuais) fica e continua na tela.

A API do YouTube é o cliente real sobre um `MockTransport`: assim o orçamento de cota e
a leitura do erro `quotaExceeded` são os de produção, e não os de um dublê.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.tema import Tema
from app.models.uso_cota_youtube import UsoCotaYoutube
from app.models.video import Video
from app.services import cota
from app.services.guarda import prazo_dos_comentarios
from app.workers import expurgo
from app.workers.youtube import ClienteYouTube
from tests.test_resultados import VIDEO_A, VIDEO_B, montar_cenario

INICIO = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)  # `iniciado_em` do cenário
VENCIDO = INICIO + prazo_dos_comentarios() + timedelta(minutes=1)
NO_PRAZO = INICIO + prazo_dos_comentarios() - timedelta(minutes=1)


def cliente_youtube(
    titulos: dict[str, str], *, status: int = 200
) -> tuple[ClienteYouTube, list[list[str]]]:
    """Cliente real, com a API respondendo `titulos` ({id: título}). Devolve os pedidos."""
    pedidos: list[list[str]] = []

    def responder(requisicao: httpx.Request) -> httpx.Response:
        ids = requisicao.url.params["id"].split(",")
        pedidos.append(ids)
        if status != 200:
            return httpx.Response(status, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
        itens = [
            {
                "id": youtube_video_id,
                "snippet": {
                    "title": titulos[youtube_video_id],
                    "channelTitle": "Canal Atual",
                    "publishedAt": "2026-09-01T12:00:00Z",
                },
                "statistics": {"viewCount": "999999", "likeCount": "9999"},
            }
            for youtube_video_id in ids
            if youtube_video_id in titulos
        ]
        return httpx.Response(200, json={"items": itens})

    http = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    return ClienteYouTube("chave-de-teste", http), pedidos


async def _comentarios(sessao, id_execucao: int) -> list[Comentario]:
    sessao.expire_all()
    return list(
        (
            await sessao.scalars(
                select(Comentario)
                .join(Video, Video.id_video == Comentario.id_video)
                .where(Video.id_execucao == id_execucao)
            )
        ).all()
    )


async def _unidades_da_empresa(sessao, id_empresa: int) -> int:
    return int(
        await sessao.scalar(
            select(func.coalesce(func.sum(UsoCotaYoutube.unidades), 0)).where(
                UsoCotaYoutube.id_empresa == id_empresa
            )
        )
    )


# --------------------------------------------------------------------------- comentários


async def test_texto_vencido_sai_e_o_resultado_fica(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="expurgo@x.com", com_temas=True)
    id_execucao = cenario["execucao"].id_execucao
    antes = (
        await cliente.get(
            f"/api/v1/execucoes/{id_execucao}/resultado", headers=cenario["cabecalho"]
        )
    ).json()

    apagadas = await expurgo.apagar_comentarios_vencidos(sessao, VENCIDO)

    assert apagadas == [id_execucao]
    comentarios = await _comentarios(sessao, id_execucao)
    assert comentarios, "a linha do comentario fica: a analise pendura nela"
    assert all(c.texto is None for c in comentarios)
    assert all(c.autor_hash is None and c.youtube_comment_id is None for c in comentarios)
    analises = (await sessao.scalars(select(AnaliseSentimento))).all()
    assert len(analises) == len(comentarios)
    assert all(a.justificativa is None for a in analises)

    depois = (
        await cliente.get(
            f"/api/v1/execucoes/{id_execucao}/resultado", headers=cenario["cabecalho"]
        )
    ).json()
    assert depois["distribuicao"] == antes["distribuicao"]
    assert depois["comentarios_apagados_em"] is not None
    assert depois["comentarios_representativos"] == []
    assert [t["comentario_representativo"] for t in depois["temas"]] == [None]
    assert depois["temas"][0]["distribuicao"] == antes["temas"][0]["distribuicao"]


async def test_lista_de_comentarios_vazia_mas_contagens_mantidas(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="lista@x.com")
    id_execucao = cenario["execucao"].id_execucao
    rota = f"/api/v1/execucoes/{id_execucao}/comentarios"
    antes = (await cliente.get(rota, headers=cenario["cabecalho"])).json()

    await expurgo.apagar_comentarios_vencidos(sessao, VENCIDO)

    depois = (await cliente.get(rota, headers=cenario["cabecalho"])).json()
    assert antes["total"] == 6
    assert depois["itens"] == []
    assert depois["total"] == 0
    assert depois["contagem_por_sentimento"] == antes["contagem_por_sentimento"]
    assert depois["comentarios_apagados_em"] is not None


async def test_texto_no_prazo_fica(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="prazo@x.com")

    assert await expurgo.apagar_comentarios_vencidos(sessao, NO_PRAZO) == []
    comentarios = await _comentarios(sessao, cenario["execucao"].id_execucao)
    assert all(c.texto for c in comentarios)


async def test_expurgo_nao_repete_o_trabalho(cliente, sessao):
    await montar_cenario(cliente, sessao, email="repete@x.com")

    assert len(await expurgo.apagar_comentarios_vencidos(sessao, VENCIDO)) == 1
    assert await expurgo.apagar_comentarios_vencidos(sessao, VENCIDO + timedelta(hours=1)) == []


async def test_prazo_nunca_passa_dos_30_dias():
    """O expurgo roda de hora em hora; apagar no 29º dia deixa a margem."""
    assert prazo_dos_comentarios() < timedelta(days=30)
    assert prazo_dos_comentarios() + timedelta(
        seconds=settings.worker_expurgo_intervalo_segundos
    ) <= (timedelta(days=30))


async def test_resultado_diz_ate_quando_os_comentarios_ficam(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="ate@x.com")
    resposta = await cliente.get(
        f"/api/v1/execucoes/{cenario['execucao'].id_execucao}/resultado",
        headers=cenario["cabecalho"],
    )

    corpo = resposta.json()
    assert corpo["comentarios_apagados_em"] is None
    assert corpo["comentarios_disponiveis_ate"].startswith("2026-10-23T10:00")


# --------------------------------------------------------------------------- vídeos


async def _envelhecer_videos(sessao, cenario, **idades: timedelta) -> None:
    """Põe `metadados_em` de cada vídeo do cenário em `VENCIDO - idade`."""
    for youtube_video_id, idade in idades.items():
        await sessao.execute(
            update(Video)
            .where(Video.id_video == ids_dos_videos(cenario)[youtube_video_id])
            .values(metadados_em=VENCIDO - idade)
        )
    await sessao.commit()


def ids_dos_videos(cenario) -> dict[str, int]:
    """Os ids lidos uma vez só: depois de `expire_all`, ler o atributo seria IO síncrono."""
    if "ids_videos" not in cenario:
        cenario["ids_videos"] = {
            chave: video.id_video for chave, video in cenario["videos"].items()
        }
    return cenario["ids_videos"]


async def _video(sessao, cenario, youtube_video_id: str) -> Video:
    sessao.expire_all()
    return await sessao.get(Video, ids_dos_videos(cenario)[youtube_video_id])


async def test_video_perto_do_prazo_e_atualizado_e_cobra_da_empresa(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="atualiza@x.com")
    await _envelhecer_videos(
        sessao,
        cenario,
        **{VIDEO_A: timedelta(days=26), VIDEO_B: timedelta(days=2)},
    )
    youtube, pedidos = cliente_youtube({VIDEO_A: "Anúncio A (novo título)"})

    atualizados, apagados = await expurgo.atualizar_videos(sessao, youtube, VENCIDO)

    assert (atualizados, apagados) == (1, 0)
    assert pedidos == [[VIDEO_A]], "o video novo nao precisa de consulta"
    id_empresa = cenario["usuario"].id_empresa
    video_a = await _video(sessao, cenario, VIDEO_A)
    assert video_a.titulo == "Anúncio A (novo título)"
    assert video_a.canal == "Canal Atual"
    # Retrato da coleta: a comparação entre coletas depende dele.
    assert (video_a.visualizacoes, video_a.curtidas) == (10_000, 500)
    assert await _unidades_da_empresa(sessao, id_empresa) == 1


async def test_video_que_saiu_do_ar_tem_titulo_apagado(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="fora@x.com")
    await _envelhecer_videos(sessao, cenario, **{VIDEO_A: timedelta(days=26)})
    youtube, _ = cliente_youtube({})

    assert await expurgo.atualizar_videos(sessao, youtube, VENCIDO) == (0, 1)
    video_a = await _video(sessao, cenario, VIDEO_A)
    assert (video_a.titulo, video_a.canal, video_a.metadados_em) == ("", "", None)


async def test_sem_cota_nao_atualiza_e_o_prazo_apaga(cliente, sessao, monkeypatch):
    cenario = await montar_cenario(cliente, sessao, email="semcota@x.com")
    await _envelhecer_videos(
        sessao,
        cenario,
        **{VIDEO_A: prazo_dos_comentarios() + timedelta(minutes=5), VIDEO_B: timedelta(days=26)},
    )

    async def sem_orcamento(*_):
        return 0

    monkeypatch.setattr(cota, "orcamento_da_empresa", sem_orcamento)
    youtube, pedidos = cliente_youtube({VIDEO_A: "x", VIDEO_B: "y"})

    assert await expurgo.atualizar_videos(sessao, youtube, VENCIDO) == (0, 0)
    assert pedidos == []
    assert await expurgo.apagar_videos_vencidos(sessao, VENCIDO) == 1
    assert (await _video(sessao, cenario, VIDEO_A)).titulo == ""
    assert (await _video(sessao, cenario, VIDEO_B)).titulo == "Anúncio B"


async def test_cota_esgotada_na_api_marca_o_dia(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="api403@x.com")
    await _envelhecer_videos(sessao, cenario, **{VIDEO_A: timedelta(days=26)})
    youtube, _ = cliente_youtube({VIDEO_A: "x"}, status=403)

    assert await expurgo.atualizar_videos(sessao, youtube, VENCIDO) == (0, 0)
    assert await cota.usado_hoje(sessao, VENCIDO) >= settings.youtube_cota_diaria
    video_a = await _video(sessao, cenario, VIDEO_A)
    assert video_a.titulo == "Anúncio A", "nao consultado: tenta de novo na proxima passada"


async def test_mesmo_video_em_duas_execucoes_custa_uma_consulta(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="dupla@x.com")
    segunda = Execucao(
        id_modelo=cenario["modelo"].id_modelo, status="concluida", iniciado_em=INICIO
    )
    sessao.add(segunda)
    await sessao.flush()
    sessao.add(
        Video(
            id_execucao=segunda.id_execucao,
            youtube_video_id=VIDEO_A,
            titulo="Anúncio A",
            canal="Loja Exemplo",
            metadados_em=VENCIDO - timedelta(days=26),
        )
    )
    await _envelhecer_videos(sessao, cenario, **{VIDEO_A: timedelta(days=26)})
    youtube, pedidos = cliente_youtube({VIDEO_A: "Novo"})

    assert await expurgo.atualizar_videos(sessao, youtube, VENCIDO) == (2, 0)
    assert pedidos == [[VIDEO_A]]


async def test_titulo_apagado_nao_quebra_o_resultado(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="semtitulo@x.com")
    await _envelhecer_videos(sessao, cenario, **{VIDEO_A: timedelta(days=40)})
    await expurgo.apagar_videos_vencidos(sessao, VENCIDO)

    resposta = await cliente.get(
        f"/api/v1/execucoes/{cenario['execucao'].id_execucao}/resultado",
        headers=cenario["cabecalho"],
    )

    assert resposta.status_code == 200
    titulos = {
        v["video"]["youtube_video_id"]: v["video"]["titulo"] for v in resposta.json()["videos"]
    }
    assert titulos == {VIDEO_A: "", VIDEO_B: "Anúncio B"}


# --------------------------------------------------------------------------- 36 meses


async def test_execucao_com_mais_de_36_meses_sai_inteira(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="velha@x.com", com_temas=True)
    id_execucao = cenario["execucao"].id_execucao
    sessao.add(Job(tipo="topicos", id_execucao=id_execucao, status="concluida"))
    await sessao.commit()
    depois_de_3_anos = INICIO + timedelta(days=settings.youtube_guarda_resultados_dias + 1)

    assert await expurgo.apagar_resultados_vencidos(sessao, depois_de_3_anos) == [id_execucao]

    modelo = type(cenario["modelo"]), cenario["modelo"].id_modelo
    sessao.expire_all()
    assert await sessao.get(Execucao, id_execucao) is None
    for tabela in (Video, Comentario, AnaliseSentimento, Tema, Job):
        assert await sessao.scalar(select(func.count()).select_from(tabela)) == 0, tabela
    assert await sessao.get(*modelo) is not None


async def test_execucao_recente_nao_e_apagada(cliente, sessao):
    await montar_cenario(cliente, sessao, email="recente@x.com")

    assert await expurgo.apagar_resultados_vencidos(sessao, VENCIDO) == []


# --------------------------------------------------------------------------- passada


async def test_passada_completa(cliente, sessao):
    cenario = await montar_cenario(cliente, sessao, email="passada@x.com")
    await _envelhecer_videos(sessao, cenario, **{VIDEO_A: timedelta(days=26)})
    youtube, _ = cliente_youtube({VIDEO_A: "Novo"})

    resumo = await expurgo.executar(sessao, youtube, VENCIDO)

    assert resumo.execucoes_com_texto_apagado == [cenario["execucao"].id_execucao]
    assert resumo.videos_atualizados == 1
    assert resumo.fez_algo


@pytest.mark.parametrize("dias", [0, 10])
async def test_passada_sem_nada_vencido_nao_faz_nada(cliente, sessao, dias):
    await montar_cenario(cliente, sessao, email=f"nada{dias}@x.com")
    for video in (await sessao.scalars(select(Video))).all():
        video.metadados_em = INICIO + timedelta(days=dias)
    await sessao.commit()
    youtube, pedidos = cliente_youtube({})

    resumo = await expurgo.executar(sessao, youtube, INICIO + timedelta(days=dias + 1))

    assert not resumo.fez_algo
    assert pedidos == []


async def test_falha_do_expurgo_nao_derruba_o_ciclo(sessao, monkeypatch, caplog):
    from app.workers import runner

    async def quebrar(*_):
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(expurgo, "executar", quebrar)

    await runner._expurgar(sessao, None)

    assert "expurgo falhou" in caplog.text
