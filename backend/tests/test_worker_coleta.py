"""Testes do worker de coleta: fila, persistência, resiliência e LGPD.

A YouTube API é sempre um dublê (`ClienteFalso`) — teste nenhum gasta cota real.
As esperas do backoff são substituídas para o teste não dormir 30s.
"""

import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import hash_token
from app.models.comentario import Comentario
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario
from app.models.video import Video
from app.workers import coleta, fila
from app.workers.youtube import (
    ComentarioColetado,
    ComentariosDesabilitados,
    ErroPermanente,
    ErroTransitorio,
    LoteComentarios,
    VideoColetado,
)

VIDEO_A = "video-a"
VIDEO_B = "video-b"
ID_CANAL_AUTOR = "UC_autor_original"


# --------------------------------------------------------------------------- dublês


class ClienteFalso:
    """Dublê da YouTube API. Registra o que foi pedido e devolve o combinado."""

    def __init__(
        self,
        *,
        videos: list[VideoColetado] | None = None,
        comentarios: dict[str, list[ComentarioColetado]] | None = None,
        erros_ate_funcionar: list[Exception] | None = None,
        erro_por_video: dict[str, Exception] | None = None,
    ) -> None:
        self.videos = videos or []
        self.comentarios = comentarios or {}
        self.erros_ate_funcionar = list(erros_ate_funcionar or [])
        self.erro_por_video = erro_por_video or {}
        self.ids_pedidos: list[list[str]] = []
        self.chamadas_de_comentario = 0
        self.pedidos_de_comentario: list[dict] = []

    def _talvez_falhar(self) -> None:
        if self.erros_ate_funcionar:
            raise self.erros_ate_funcionar.pop(0)

    async def listar_videos(self, ids):
        self.ids_pedidos.append(list(ids))
        self._talvez_falhar()
        return [v for v in self.videos if v.youtube_video_id in set(ids)]

    async def listar_comentarios(
        self,
        youtube_video_id: str,
        limite: int,
        *,
        publicado_apos=None,
        aceitar_texto=None,
        max_lidos=None,
    ) -> LoteComentarios:
        """Aplica os filtros como o cliente real (a paginação é testada lá)."""
        self.chamadas_de_comentario += 1
        self.pedidos_de_comentario.append(
            {
                "video": youtube_video_id,
                "limite": limite,
                "publicado_apos": publicado_apos,
                "max_lidos": max_lidos,
            }
        )
        self._talvez_falhar()
        if youtube_video_id in self.erro_por_video:
            raise self.erro_por_video[youtube_video_id]

        lote = LoteComentarios()
        for item in self.comentarios.get(youtube_video_id, []):
            if len(lote.comentarios) >= limite or (
                max_lidos is not None and lote.lidos >= max_lidos
            ):
                break
            lote.lidos += 1
            if publicado_apos is not None and item.publicado_em < publicado_apos:
                lote.descartados_por_data += 1
                continue
            if aceitar_texto is not None and not aceitar_texto(item.texto):
                lote.descartados_por_termo += 1
                continue
            lote.comentarios.append(item)
        return lote


def video(youtube_video_id: str = VIDEO_A, **campos) -> VideoColetado:
    padrao = {
        "titulo": "Campanha de verão",
        "canal": "Loja Exemplo",
        "publicado_em": None,
        "visualizacoes": 1000,
        "curtidas": 50,
    }
    return VideoColetado(youtube_video_id=youtube_video_id, **{**padrao, **campos})


def comentario(
    id_comentario: str, *, texto: str | None = None, publicado_em: datetime | None = None
) -> ComentarioColetado:
    return ComentarioColetado(
        youtube_comment_id=id_comentario,
        autor_hash=hash_token(ID_CANAL_AUTOR),
        texto=texto if texto is not None else f"texto de {id_comentario}",
        publicado_em=publicado_em,
    )


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    """Backoff sem dormir de verdade: o teste verifica a lógica, não o relógio."""
    esperas: list[float] = []

    async def _fake(segundos: float) -> None:
        esperas.append(segundos)

    monkeypatch.setattr(coleta, "_esperar", _fake)
    return esperas


# --------------------------------------------------------------------------- cenário


async def montar_job(sessao, *, filtros: dict | None = None, termo: str = "") -> Job:
    """Cria usuário -> modelo -> execução -> job de coleta pendente, direto no banco."""
    usuario = Usuario(
        nome="Dona", email=f"dona{id(filtros)}@exemplo.com", senha_hash="x", papel="usuario_pme"
    )
    sessao.add(usuario)
    await sessao.flush()

    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario,
        nome="Campanha",
        termo_pesquisa=termo,
        filtros=filtros if filtros is not None else {"videos": [VIDEO_A]},
    )
    sessao.add(modelo)
    await sessao.flush()

    execucao = Execucao(id_modelo=modelo.id_modelo, status="pendente")
    sessao.add(execucao)
    await sessao.flush()

    job = Job(
        tipo="coleta",
        id_execucao=execucao.id_execucao,
        status="pendente",
        payload={
            "id_modelo": modelo.id_modelo,
            "termo_pesquisa": termo,
            "filtros": modelo.filtros,
        },
    )
    sessao.add(job)
    await sessao.commit()
    await sessao.refresh(job)
    return job


# --------------------------------------------------------------------------- fila


async def test_reivindicar_marca_job_e_execucao_como_processando(sessao):
    job = await montar_job(sessao)

    reivindicado = await fila.reivindicar(sessao, "coleta")

    assert reivindicado.id_job == job.id_job
    assert reivindicado.status == "processando"
    execucao = await sessao.get(Execucao, job.id_execucao)
    assert execucao.status == "processando"
    assert execucao.iniciado_em is not None


async def test_reivindicar_devolve_none_com_fila_vazia(sessao):
    assert await fila.reivindicar(sessao, "coleta") is None


async def test_reivindicar_ignora_job_de_outro_tipo(sessao):
    job = await montar_job(sessao)
    job.tipo = "inferencia"
    await sessao.commit()

    assert await fila.reivindicar(sessao, "coleta") is None


async def test_job_ja_processando_nao_e_reivindicado_de_novo(sessao):
    await montar_job(sessao)
    await fila.reivindicar(sessao, "coleta")

    assert await fila.reivindicar(sessao, "coleta") is None


# --------------------------------------------------------------------------- caminho feliz


async def test_coleta_persiste_videos_e_comentarios(sessao):
    job = await montar_job(sessao)
    cliente = ClienteFalso(
        videos=[video()], comentarios={VIDEO_A: [comentario("c1"), comentario("c2")]}
    )

    assert await coleta.executar_proximo(sessao, cliente) is True

    videos = (await sessao.scalars(select(Video))).all()
    assert len(videos) == 1
    assert videos[0].youtube_video_id == VIDEO_A
    assert videos[0].titulo == "Campanha de verão"
    assert videos[0].visualizacoes == 1000
    assert videos[0].id_execucao == job.id_execucao

    comentarios = (await sessao.scalars(select(Comentario))).all()
    assert len(comentarios) == 2
    assert {c.id_video for c in comentarios} == {videos[0].id_video}


async def test_ao_terminar_publica_inferencia_e_mantem_execucao_processando(sessao):
    """A coleta NAO encerra a execucao: ela passa o bastao para a inferencia.

    Comentario coletado sem classificacao nao e resultado nenhum para a PME -- se a
    execucao virasse 'concluida' aqui, o painel anunciaria pronto um resultado que
    ainda nao existe.
    """
    job = await montar_job(sessao)
    cliente = ClienteFalso(videos=[video()], comentarios={VIDEO_A: [comentario("c1")]})

    await coleta.executar_proximo(sessao, cliente)

    await sessao.refresh(job)
    assert job.status == "concluida"

    execucao = await sessao.get(Execucao, job.id_execucao)
    assert execucao.status == "processando"
    assert execucao.concluido_em is None

    proximo = (await sessao.scalars(select(Job).where(Job.tipo == "inferencia"))).all()
    assert len(proximo) == 1
    assert proximo[0].id_execucao == job.id_execucao
    assert proximo[0].status == "pendente"


async def test_job_de_inferencia_nasce_na_mesma_transacao_da_conclusao(sessao):
    """Atomicidade: nunca existe o instante 'coleta concluida, nada na fila'.

    Se as duas escritas fossem transacoes separadas e o worker morresse entre elas, a
    execucao ficaria 'processando' para sempre, sem job para ninguem buscar.
    """
    job = await montar_job(sessao)
    cliente = ClienteFalso(videos=[video()], comentarios={VIDEO_A: [comentario("c1")]})
    commits: list[tuple[str, str | None]] = []

    commit_original = sessao.commit

    async def espiar_commit():
        await commit_original()
        coletado = await sessao.get(Job, job.id_job)
        seguinte = await sessao.scalar(select(Job).where(Job.tipo == "inferencia"))
        commits.append((coletado.status if coletado else None, seguinte.tipo if seguinte else None))

    sessao.commit = espiar_commit
    try:
        await coleta.executar_proximo(sessao, cliente)
    finally:
        sessao.commit = commit_original

    # Em nenhum commit o job de coleta aparece concluido sem a etapa seguinte no banco.
    assert ("concluida", None) not in commits
    assert ("concluida", "inferencia") in commits


async def test_falha_na_coleta_nao_publica_inferencia(sessao):
    """Sem comentario nenhum nao ha o que classificar: a cadeia para na falha."""
    job = await montar_job(sessao, filtros={"videos": []})

    await coleta.executar_proximo(sessao, ClienteFalso())

    assert await sessao.scalar(select(Job).where(Job.tipo == "inferencia")) is None
    execucao = await sessao.get(Execucao, job.id_execucao)
    assert execucao.status == "erro"


async def test_executar_proximo_sem_job_devolve_false(sessao):
    assert await coleta.executar_proximo(sessao, ClienteFalso()) is False


async def test_varios_videos_na_mesma_execucao(sessao):
    await montar_job(sessao, filtros={"videos": [VIDEO_A, VIDEO_B]})
    cliente = ClienteFalso(
        videos=[video(VIDEO_A), video(VIDEO_B)],
        comentarios={VIDEO_A: [comentario("a1")], VIDEO_B: [comentario("b1"), comentario("b2")]},
    )

    await coleta.executar_proximo(sessao, cliente)

    assert len((await sessao.scalars(select(Video))).all()) == 2
    assert len((await sessao.scalars(select(Comentario))).all()) == 3


# --------------------------------------------------------------------------- payload congelado


async def test_worker_usa_o_payload_e_nunca_rele_o_modelo(sessao):
    """Reprodutibilidade: editar o modelo depois do disparo não muda a coleta."""
    job = await montar_job(sessao, filtros={"videos": [VIDEO_A]})

    modelo = await sessao.get(ModeloAnalise, job.payload["id_modelo"])
    modelo.filtros = {"videos": [VIDEO_B]}
    modelo.termo_pesquisa = "outro termo"
    await sessao.commit()

    cliente = ClienteFalso(videos=[video(VIDEO_A), video(VIDEO_B)])
    await coleta.executar_proximo(sessao, cliente)

    assert cliente.ids_pedidos == [[VIDEO_A]]
    videos = (await sessao.scalars(select(Video))).all()
    assert [v.youtube_video_id for v in videos] == [VIDEO_A]


# --------------------------------------------------------------------------- LGPD


async def test_so_o_hash_do_autor_e_persistido(sessao):
    """CLAUDE.md regra 2: nome, canal ou ID do autor não podem entrar no banco."""
    await montar_job(sessao)
    cliente = ClienteFalso(videos=[video()], comentarios={VIDEO_A: [comentario("c1")]})

    await coleta.executar_proximo(sessao, cliente)

    gravado = await sessao.scalar(select(Comentario))
    assert gravado.autor_hash == hash_token(ID_CANAL_AUTOR)
    assert len(gravado.autor_hash) == 64
    assert ID_CANAL_AUTOR not in str(gravado.__dict__)


# --------------------------------------------------------------------------- filtros


async def test_chave_desconhecida_no_filtro_gera_aviso(sessao, caplog):
    """Combinado no UC02 por causa do extra='allow'."""
    await montar_job(sessao, filtros={"videos": [VIDEO_A], "idioma": "pt", "min_curtidas": 10})
    cliente = ClienteFalso(videos=[video()])

    with caplog.at_level(logging.WARNING):
        await coleta.executar_proximo(sessao, cliente)

    avisos = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("chave(s) desconhecida(s)" in a for a in avisos)
    assert any("idioma" in a and "min_curtidas" in a for a in avisos)


async def test_filtro_canais_avisa_que_nao_e_expandido(sessao, caplog):
    await montar_job(sessao, filtros={"videos": [VIDEO_A], "canais": ["UCabc"]})
    cliente = ClienteFalso(videos=[video()])

    with caplog.at_level(logging.WARNING):
        await coleta.executar_proximo(sessao, cliente)

    assert any("canais" in r.getMessage() for r in caplog.records)


async def test_filtro_sem_video_nenhum_manda_para_a_dlq(sessao):
    job = await montar_job(sessao, filtros={"canais": ["UCabc"]})

    await coleta.executar_proximo(sessao, ClienteFalso())

    dlq = await sessao.scalar(select(JobDlq))
    assert dlq.id_job == job.id_job
    assert "Nenhum ID de vídeo" in dlq.erro
    execucao = await sessao.get(Execucao, job.id_execucao)
    assert execucao.status == "erro"


async def test_video_do_filtro_que_a_api_nao_devolve_gera_aviso(sessao, caplog):
    await montar_job(sessao, filtros={"videos": [VIDEO_A, "video-removido"]})
    cliente = ClienteFalso(videos=[video(VIDEO_A)])

    with caplog.at_level(logging.WARNING):
        await coleta.executar_proximo(sessao, cliente)

    assert any("video-removido" in r.getMessage() for r in caplog.records)
    assert len((await sessao.scalars(select(Video))).all()) == 1


# --------------------------------------------------------------------------- comentários off


async def test_video_com_comentarios_desabilitados_fica_com_zero(sessao):
    job = await montar_job(sessao, filtros={"videos": [VIDEO_A, VIDEO_B]})
    cliente = ClienteFalso(
        videos=[video(VIDEO_A), video(VIDEO_B)],
        comentarios={VIDEO_B: [comentario("b1")]},
        erro_por_video={VIDEO_A: ComentariosDesabilitados("commentsDisabled")},
    )

    await coleta.executar_proximo(sessao, cliente)

    videos = {v.youtube_video_id: v for v in (await sessao.scalars(select(Video))).all()}
    assert set(videos) == {VIDEO_A, VIDEO_B}

    comentarios = (await sessao.scalars(select(Comentario))).all()
    assert len(comentarios) == 1
    assert comentarios[0].id_video == videos[VIDEO_B].id_video

    # a execução inteira não pode falhar por causa de um vídeo sem comentários
    await sessao.refresh(job)
    assert job.status == "concluida"
    execucao = await sessao.get(Execucao, job.id_execucao)
    assert execucao.status == "processando"  # segue para a inferência


# --------------------------------------------------------------------------- resiliência


async def test_erro_transitorio_e_repetido_ate_dar_certo(sessao, sem_espera):
    await montar_job(sessao)
    cliente = ClienteFalso(
        videos=[video()],
        comentarios={VIDEO_A: [comentario("c1")]},
        erros_ate_funcionar=[ErroTransitorio("429"), ErroTransitorio("503")],
    )

    await coleta.executar_proximo(sessao, cliente)

    assert len((await sessao.scalars(select(Video))).all()) == 1
    assert len(sem_espera) == 2


async def test_backoff_e_exponencial_com_jitter(sessao, sem_espera):
    await montar_job(sessao)
    cliente = ClienteFalso(
        videos=[video()],
        erros_ate_funcionar=[ErroTransitorio("1"), ErroTransitorio("2"), ErroTransitorio("3")],
    )

    await coleta.executar_proximo(sessao, cliente)

    assert len(sem_espera) == 3
    # 2, 4, 8 (+ jitter de até 1s)
    assert 2 <= sem_espera[0] < 3
    assert 4 <= sem_espera[1] < 5
    assert 8 <= sem_espera[2] < 9


async def test_tentativas_esgotadas_vao_para_a_dlq(sessao, sem_espera):
    job = await montar_job(sessao)
    cliente = ClienteFalso(erros_ate_funcionar=[ErroTransitorio("429")] * 10)

    await coleta.executar_proximo(sessao, cliente)

    dlq = await sessao.scalar(select(JobDlq))
    assert dlq.id_job == job.id_job
    assert dlq.tipo == "coleta"
    assert "esgotadas" in dlq.erro

    execucao = await sessao.get(Execucao, job.id_execucao)
    assert execucao.status == "erro"
    assert execucao.concluido_em is not None

    # o job sai da fila para não ser reivindicado de novo
    assert (await sessao.scalars(select(Job))).all() == []


async def test_numero_de_tentativas_respeita_o_maximo(sessao, sem_espera):
    """worker_max_retries=4 -> 4 esperas (2, 4, 8, 16) e 5 chamadas à API."""
    await montar_job(sessao)
    cliente = ClienteFalso(erros_ate_funcionar=[ErroTransitorio("429")] * 10)

    await coleta.executar_proximo(sessao, cliente)

    assert len(sem_espera) == 4
    assert len(cliente.ids_pedidos) == 5


async def test_erro_permanente_nao_e_repetido(sessao, sem_espera):
    job = await montar_job(sessao)
    cliente = ClienteFalso(erros_ate_funcionar=[ErroPermanente("403 chave invalida")])

    await coleta.executar_proximo(sessao, cliente)

    assert sem_espera == []
    assert len(cliente.ids_pedidos) == 1
    dlq = await sessao.scalar(select(JobDlq))
    assert dlq.id_job == job.id_job
    execucao = await sessao.get(Execucao, job.id_execucao)
    assert execucao.status == "erro"


async def test_falha_nao_deixa_video_pela_metade(sessao, sem_espera):
    """A coleta commita uma vez só: execução com erro não fica com dados parciais."""
    await montar_job(sessao, filtros={"videos": [VIDEO_A, VIDEO_B]})
    cliente = ClienteFalso(
        videos=[video(VIDEO_A), video(VIDEO_B)],
        comentarios={VIDEO_A: [comentario("a1")]},
        erro_por_video={VIDEO_B: ErroPermanente("403")},
    )

    await coleta.executar_proximo(sessao, cliente)

    assert (await sessao.scalars(select(Video))).all() == []
    assert (await sessao.scalars(select(Comentario))).all() == []
    assert await sessao.scalar(select(JobDlq)) is not None


# --------------------------------------------------------------------------- teto


async def test_teto_de_comentarios_por_execucao(sessao, monkeypatch):
    monkeypatch.setattr(coleta.settings, "worker_max_comentarios_por_execucao", 3)
    await montar_job(sessao, filtros={"videos": [VIDEO_A, VIDEO_B]})
    cliente = ClienteFalso(
        videos=[video(VIDEO_A), video(VIDEO_B)],
        comentarios={
            VIDEO_A: [comentario(f"a{n}") for n in range(5)],
            VIDEO_B: [comentario("b1")],
        },
    )

    await coleta.executar_proximo(sessao, cliente)

    assert len((await sessao.scalars(select(Comentario))).all()) == 3


# --------------------------------------------------------------------------- reexecução


async def test_o_mesmo_video_pode_ser_coletado_em_outra_execucao(sessao):
    """Unicidade é por execução: rodar o modelo de novo não pode dar conflito."""
    await montar_job(sessao, filtros={"videos": [VIDEO_A]})
    cliente = ClienteFalso(videos=[video()], comentarios={VIDEO_A: [comentario("c1")]})
    await coleta.executar_proximo(sessao, cliente)

    await montar_job(sessao, filtros={"videos": [VIDEO_A]})
    cliente = ClienteFalso(videos=[video()], comentarios={VIDEO_A: [comentario("c1")]})
    await coleta.executar_proximo(sessao, cliente)

    videos = (await sessao.scalars(select(Video))).all()
    assert len(videos) == 2
    assert len({v.id_execucao for v in videos}) == 2
    assert len((await sessao.scalars(select(Comentario))).all()) == 2
    assert (await sessao.scalars(select(JobDlq))).all() == []


# --------------------------------------------------------------------------- filtros


async def _textos_gravados(sessao) -> list[str]:
    return list(
        (await sessao.scalars(select(Comentario.texto).order_by(Comentario.id_comentario))).all()
    )


async def test_limite_informado_vale_para_a_execucao_inteira(sessao):
    """O limite é da execução, repartido entre os vídeos — não por vídeo."""
    await montar_job(sessao, filtros={"videos": [VIDEO_A, VIDEO_B], "limite_comentarios": 4})
    cliente = ClienteFalso(
        videos=[video(VIDEO_A), video(VIDEO_B)],
        comentarios={
            VIDEO_A: [comentario(f"a{n}") for n in range(3)],
            VIDEO_B: [comentario(f"b{n}") for n in range(3)],
        },
    )

    await coleta.executar_proximo(sessao, cliente)

    assert await _textos_gravados(sessao) == [
        "texto de a0",
        "texto de a1",
        "texto de a2",
        "texto de b0",
    ]
    assert [p["limite"] for p in cliente.pedidos_de_comentario] == [4, 1]


async def test_limite_acima_do_teto_vale_o_teto(sessao, monkeypatch):
    monkeypatch.setattr(coleta.settings, "worker_max_comentarios_por_execucao", 3)
    job = await montar_job(sessao, filtros={"videos": [VIDEO_A], "limite_comentarios": 10})
    cliente = ClienteFalso(
        videos=[video()], comentarios={VIDEO_A: [comentario(f"a{n}") for n in range(5)]}
    )

    await coleta.executar_proximo(sessao, cliente)
    await sessao.refresh(job)

    assert len(await _textos_gravados(sessao)) == 3
    recorte = job.payload[coleta.CHAVE_RECORTE]
    assert (recorte["limite_informado"], recorte["limite_aplicado"]) == (10, 3)


async def test_data_minima_vira_meia_noite_de_brasilia(sessao):
    """ "A partir de 01/09" para uma PME brasileira começa às 00:00 de Brasília (03:00 UTC)."""
    await montar_job(sessao, filtros={"videos": [VIDEO_A], "publicado_apos": "2026-09-01"})
    brasilia = timezone(timedelta(hours=-3))
    cliente = ClienteFalso(
        videos=[video()],
        comentarios={
            VIDEO_A: [
                comentario("dentro", publicado_em=datetime(2026, 9, 1, 0, 30, tzinfo=brasilia)),
                # 31/08 às 23h em Brasília: já é 01/09 em UTC, e mesmo assim fica de fora.
                comentario("fora", publicado_em=datetime(2026, 9, 1, 2, 0, tzinfo=UTC)),
            ]
        },
    )

    await coleta.executar_proximo(sessao, cliente)

    assert cliente.pedidos_de_comentario[0]["publicado_apos"] == datetime(
        2026, 9, 1, tzinfo=brasilia
    )
    assert await _textos_gravados(sessao) == ["texto de dentro"]


async def test_termo_de_pesquisa_filtra_sem_diferenciar_maiusculas_e_acentos(sessao):
    """A tela promete "comentários que contenham este termo": a coleta cumpre."""
    await montar_job(sessao, termo="Tênis")
    cliente = ClienteFalso(
        videos=[video()],
        comentarios={
            VIDEO_A: [
                comentario("c1", texto="Esse TENIS é lindo"),
                comentario("c2", texto="não gostei da música"),
                comentario("c3", texto="meu tênis chegou rasgado"),
            ]
        },
    )

    await coleta.executar_proximo(sessao, cliente)

    assert await _textos_gravados(sessao) == ["Esse TENIS é lindo", "meu tênis chegou rasgado"]


def test_normalizar_tira_acento_e_caixa():
    assert coleta.normalizar("AÇÃO Promoção") == "acao promocao"
    assert coleta.contem_termo("promoção")("Que PROMOCAO boa!")
    assert not coleta.contem_termo("promoção")("que preço bom")


async def test_recorte_aplicado_fica_registrado_no_job_sem_mexer_no_pedido(sessao):
    job = await montar_job(
        sessao,
        termo="tênis",
        filtros={"videos": [VIDEO_A], "publicado_apos": "2026-09-01", "limite_comentarios": 50},
    )
    pedido = dict(job.payload)
    cliente = ClienteFalso(
        videos=[video()],
        comentarios={
            VIDEO_A: [
                comentario("c1", texto="tênis bom", publicado_em=datetime(2026, 9, 5, tzinfo=UTC)),
                comentario("c2", texto="sapato", publicado_em=datetime(2026, 9, 4, tzinfo=UTC)),
                comentario("c3", texto="tênis", publicado_em=datetime(2026, 8, 1, tzinfo=UTC)),
            ]
        },
    )

    await coleta.executar_proximo(sessao, cliente)
    await sessao.refresh(job)

    recorte = job.payload.pop(coleta.CHAVE_RECORTE)
    assert job.payload == pedido  # o pedido congelado no disparo não muda
    assert datetime.fromisoformat(recorte.pop("coletado_em")).tzinfo is not None
    assert recorte == {
        "termo_pesquisa": "tênis",
        "publicado_apos": "2026-09-01",
        "limite_informado": 50,
        "limite_aplicado": 50,
        "comentarios_lidos": 3,
        "comentarios_coletados": 1,
        "descartados_por_data": 1,
        "descartados_por_termo": 1,
    }


async def test_teto_de_leitura_e_da_execucao(sessao, monkeypatch):
    monkeypatch.setattr(coleta.settings, "worker_max_comentarios_lidos_por_execucao", 5)
    await montar_job(sessao, termo="nada casa", filtros={"videos": [VIDEO_A, VIDEO_B]})
    cliente = ClienteFalso(
        videos=[video(VIDEO_A), video(VIDEO_B)],
        comentarios={
            VIDEO_A: [comentario(f"a{n}") for n in range(3)],
            VIDEO_B: [comentario(f"b{n}") for n in range(10)],
        },
    )

    await coleta.executar_proximo(sessao, cliente)

    assert [p["max_lidos"] for p in cliente.pedidos_de_comentario] == [5, 2]


@pytest.mark.parametrize(
    "filtros_tortos",
    [
        {"publicado_apos": "01/09/2026"},
        {"limite_comentarios": "100"},
        {"limite_comentarios": 0},
        {"limite_comentarios": True},
    ],
)
async def test_filtro_invalido_de_modelo_antigo_e_ignorado_com_aviso(
    sessao, caplog, filtros_tortos
):
    """O cadastro recusa; o que chega torto é modelo salvo antes da validação."""
    await montar_job(sessao, filtros={"videos": [VIDEO_A], **filtros_tortos})
    cliente = ClienteFalso(videos=[video()], comentarios={VIDEO_A: [comentario("c1")]})

    with caplog.at_level(logging.WARNING):
        await coleta.executar_proximo(sessao, cliente)

    assert "invalido, ignorado" in caplog.text
    assert len(await _textos_gravados(sessao)) == 1
    assert (await sessao.scalars(select(JobDlq))).all() == []
