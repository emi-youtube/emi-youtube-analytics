"""Cota diária da YouTube Data API: contar, repartir e esperar (ADR-015).

Nenhum teste toca a rede: o cliente usa `httpx.MockTransport` e a coleta usa o dublê
de `test_worker_coleta`. Gastar cota real num teste é inaceitável.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.empresa import Empresa
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.uso_cota_youtube import ID_AJUSTE, UsoCotaYoutube
from app.models.usuario import Usuario
from app.models.video import Video
from app.services import cota
from app.services.execucao import anexar_espera, esperas
from app.workers import coleta, fila
from app.workers.youtube import (
    ClienteYouTube,
    CotaEsgotada,
    ErroPermanente,
    ErroTransitorio,
)

from .conftest import autenticar
from .test_execucoes import ROTA, criar_modelo, disparar
from .test_worker_coleta import (  # noqa: F401
    ClienteFalso,
    comentario,
    montar_job,
    sem_espera,
    video,
)

VERAO = datetime(2026, 7, 15, 20, 0, tzinfo=UTC)  # 13h em Los Angeles (PDT, UTC-7)
INVERNO = datetime(2026, 12, 15, 20, 0, tzinfo=UTC)  # 12h em Los Angeles (PST, UTC-8)


# --------------------------------------------------------------------------- relógio


def test_renovacao_e_meia_noite_do_pacifico_no_verao():
    # 00:00 PDT = 07:00 UTC do dia seguinte.
    assert cota.proxima_renovacao(VERAO) == datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def test_renovacao_acompanha_o_horario_de_verao():
    # No inverno o Pacífico é UTC-8: o mesmo "meia-noite" cai uma hora depois no UTC.
    assert cota.proxima_renovacao(INVERNO) == datetime(2026, 12, 16, 8, 0, tzinfo=UTC)


def test_dia_da_cota_nao_e_o_de_brasilia():
    # 02h UTC de 16/07 ainda é 15/07 em Los Angeles: a cota de ontem continua valendo.
    assert cota.dia_da_cota(datetime(2026, 7, 16, 2, 0, tzinfo=UTC)).isoformat() == "2026-07-15"


def test_estimativa_de_custo_e_pequena_e_limitada_pela_fatia():
    # 5.000 comentários = 50 páginas + 1 página final + 1 videos.list.
    assert cota.estimar_custo(1, 5000) == 52
    assert cota.estimar_custo(1, 10**9) == settings.youtube_cota_fatia_por_empresa


# --------------------------------------------------------------------------- orçamento


async def test_dia_vazio_libera_ate_a_folga_compartilhada(sessao):
    assert await cota.orcamento_da_empresa(sessao, 1, VERAO) == 7000


async def test_reserva_nunca_e_gasta(sessao):
    await cota.registrar_uso(sessao, 1, 9400, VERAO)
    await cota.registrar_uso(sessao, 2, 0, VERAO)  # zero não grava

    assert await cota.orcamento_da_empresa(sessao, 2, VERAO) == 100  # 10000 - 500 - 9400


async def test_empresa_que_estourou_a_fatia_espera_quando_o_dia_passa_da_folga(sessao):
    await cota.registrar_uso(sessao, 1, 6000, VERAO)  # a empresa 1 usou 3x a fatia
    await cota.registrar_uso(sessao, 2, 1100, VERAO)  # total 7100: passou de 70%

    assert await cota.orcamento_da_empresa(sessao, 1, VERAO) == 0
    # A empresa 2 gastou menos que a fatia (2000): ainda tem o resto, 900.
    assert await cota.orcamento_da_empresa(sessao, 2, VERAO) == 900


async def test_empresa_nova_tem_a_fatia_mesmo_com_o_dia_cheio(sessao):
    await cota.registrar_uso(sessao, 1, 8000, VERAO)

    assert await cota.orcamento_da_empresa(sessao, 99, VERAO) == 1500  # limitada pelo dia


async def test_cada_dia_tem_a_sua_conta(sessao):
    await cota.registrar_uso(sessao, 1, 8000, VERAO)
    amanha = VERAO + timedelta(days=1)

    assert await cota.orcamento_da_empresa(sessao, 1, amanha) == 7000


async def test_registrar_soma_e_nao_substitui(sessao):
    await cota.registrar_uso(sessao, 1, 40, VERAO)
    await cota.registrar_uso(sessao, 1, 2, VERAO)

    linhas = (await sessao.scalars(select(UsoCotaYoutube))).all()
    assert [(linha.id_empresa, linha.unidades) for linha in linhas] == [(1, 42)]


async def test_historico_antigo_sai_na_propria_escrita(sessao):
    await cota.registrar_uso(sessao, 1, 10, VERAO - timedelta(days=60))
    await cota.registrar_uso(sessao, 1, 10, VERAO)

    dias = {linha.dia for linha in (await sessao.scalars(select(UsoCotaYoutube))).all()}
    assert dias == {cota.dia_da_cota(VERAO)}


async def test_api_disse_que_acabou_zera_o_orcamento_de_todos(sessao):
    await cota.registrar_uso(sessao, 1, 300, VERAO)

    await cota.marcar_esgotada(sessao, VERAO)

    assert await cota.usado_hoje(sessao, VERAO) == settings.youtube_cota_diaria
    assert await cota.orcamento_da_empresa(sessao, 2, VERAO) == 0
    ajuste = await sessao.get(UsoCotaYoutube, (cota.dia_da_cota(VERAO), ID_AJUSTE))
    assert ajuste.unidades == settings.youtube_cota_diaria - 300


# --------------------------------------------------------------------------- cliente


def cliente_com(handler) -> ClienteYouTube:
    return ClienteYouTube("chave", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def resposta_vazia(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"items": []})


def erro_403(motivo: str):
    corpo = {"error": {"errors": [{"reason": motivo}]}}
    return lambda _: httpx.Response(403, json=corpo)


async def test_medir_conta_uma_unidade_por_chamada():
    cliente = cliente_com(resposta_vazia)

    with cliente.medir() as medida:
        await cliente.listar_videos(["a"])
        await cliente.listar_comentarios("a", 10)

    assert medida.unidades == 2


async def test_chamada_que_estouraria_o_orcamento_nem_sai():
    chamadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request)
        return httpx.Response(200, json={"items": []})

    cliente = cliente_com(handler)

    with cliente.medir(1) as medida, pytest.raises(CotaEsgotada) as erro:
        await cliente.listar_videos(["a"])
        await cliente.listar_comentarios("a", 10)

    assert len(chamadas) == 1
    assert medida.unidades == 1
    assert erro.value.da_api is False


@pytest.mark.parametrize("motivo", ["quotaExceeded", "dailyLimitExceeded"])
async def test_cota_diaria_da_api_vira_cota_esgotada(motivo):
    cliente = cliente_com(erro_403(motivo))

    with pytest.raises(CotaEsgotada) as erro:
        await cliente.listar_videos(["a"])

    assert erro.value.da_api is True
    assert not isinstance(erro.value, ErroPermanente)  # não pode virar falha definitiva


@pytest.mark.parametrize("motivo", ["rateLimitExceeded", "userRateLimitExceeded"])
async def test_limite_por_segundo_e_transitorio(motivo):
    cliente = cliente_com(erro_403(motivo))

    with pytest.raises(ErroTransitorio):
        await cliente.listar_videos(["a"])


async def test_outro_403_continua_permanente():
    cliente = cliente_com(erro_403("forbidden"))

    with pytest.raises(ErroPermanente):
        await cliente.listar_videos(["a"])


async def test_sem_medir_o_cliente_se_comporta_como_antes():
    cliente = cliente_com(resposta_vazia)

    assert await cliente.listar_videos(["a"]) == []


# --------------------------------------------------------------------------- coleta


class ClienteSemCota(ClienteFalso):
    """Estoura a cota na primeira busca de comentários, depois de gravar o vídeo."""

    async def listar_comentarios(self, *args, **kwargs):
        raise CotaEsgotada("a cota diária da YouTube API acabou", da_api=True)


async def empresa_do(sessao, job: Job) -> int:
    return await coleta._empresa_da_execucao(sessao, job.id_execucao)


async def test_sem_orcamento_a_coleta_espera_e_nao_chama_a_api(sessao):
    job = await montar_job(sessao)
    id_empresa = await empresa_do(sessao, job)
    await cota.registrar_uso(sessao, id_empresa, 6000)
    await cota.registrar_uso(sessao, 999, 1100)
    cliente = ClienteFalso(videos=[video()], comentarios={"video-a": [comentario("c1")]})

    assert await coleta.executar_proximo(sessao, cliente) is True

    assert cliente.ids_pedidos == []  # nem metadados: nada foi gasto
    await sessao.refresh(job)
    assert job.status == "pendente"
    assert job.disponivel_em is not None
    assert job.motivo_espera == cota.MOTIVO_COTA
    assert (await sessao.scalars(select(JobDlq))).all() == []
    assert (await sessao.get(Execucao, job.id_execucao)).status == "pendente"


async def test_job_adiado_so_e_reivindicado_depois_da_hora(sessao):
    job = await montar_job(sessao)
    id_empresa = await empresa_do(sessao, job)
    await cota.registrar_uso(sessao, id_empresa, 6000)
    await cota.registrar_uso(sessao, 999, 1100)
    await coleta.executar_proximo(sessao, ClienteFalso())

    assert await fila.reivindicar(sessao, "coleta") is None  # ainda espera

    await sessao.refresh(job)
    job.disponivel_em = datetime.now(UTC) - timedelta(minutes=1)
    await sessao.commit()
    reivindicado = await fila.reivindicar(sessao, "coleta")

    assert reivindicado is not None
    assert reivindicado.disponivel_em is None
    assert reivindicado.motivo_espera is None


async def test_cota_que_acaba_no_meio_descarta_o_parcial_e_adia(sessao):
    job = await montar_job(sessao)
    cliente = ClienteSemCota(videos=[video()])

    await coleta.executar_proximo(sessao, cliente)

    await sessao.refresh(job)
    assert job.status == "pendente"
    assert job.disponivel_em is not None
    assert job.tentativas == 0
    assert (await sessao.scalars(select(JobDlq))).all() == []
    assert (await sessao.scalars(select(Video))).all() == []  # nada parcial fica
    # A API disse que acabou: o dia inteiro passa a esperar, sem bater nela de novo.
    assert await cota.usado_hoje(sessao) >= settings.youtube_cota_diaria


async def test_coleta_que_conclui_registra_o_que_gastou(sessao):
    job = await montar_job(sessao)
    id_empresa = await empresa_do(sessao, job)
    cliente = ClienteFalso(videos=[video()], comentarios={"video-a": [comentario("c1")]})
    cliente.unidades_por_job = 3

    await coleta.executar_proximo(sessao, cliente)

    assert cliente.orcamentos_recebidos == [7000]
    uso = await sessao.get(UsoCotaYoutube, (cota.dia_da_cota(datetime.now(UTC)), id_empresa))
    assert uso.unidades == 3


async def test_coleta_que_falha_tambem_registra_o_gasto(sessao):
    job = await montar_job(sessao)
    id_empresa = await empresa_do(sessao, job)
    cliente = ClienteFalso(erros_ate_funcionar=[ErroPermanente("400 requisicao recusada")])
    cliente.unidades_por_job = 1

    await coleta.executar_proximo(sessao, cliente)

    assert len((await sessao.scalars(select(JobDlq))).all()) == 1
    uso = await sessao.get(UsoCotaYoutube, (cota.dia_da_cota(datetime.now(UTC)), id_empresa))
    assert uso.unidades == 1


# --------------------------------------------------------------------------- o que a tela vê


async def test_execucao_adiada_informa_quando_volta(cliente, sessao):
    headers = await autenticar(cliente, "cota@exemplo.com")
    modelo = await criar_modelo(cliente, headers)
    id_execucao = (await disparar(cliente, headers, modelo["id_modelo"])).json()["id_execucao"]
    job = await sessao.scalar(select(Job).where(Job.id_execucao == id_execucao))
    volta = datetime.now(UTC) + timedelta(hours=3)
    await fila.adiar(sessao, job, volta, cota.MOTIVO_COTA)

    lista = (await cliente.get(ROTA, headers=headers)).json()
    detalhe = (await cliente.get(f"{ROTA}/{id_execucao}", headers=headers)).json()

    assert lista[0]["retoma_em"] is not None
    assert detalhe["retoma_em"] is not None
    assert detalhe["status"] == "pendente"


async def test_execucao_comum_na_fila_nao_tem_hora_de_volta(cliente):
    headers = await autenticar(cliente, "cota2@exemplo.com")
    modelo = await criar_modelo(cliente, headers)

    corpo = (await disparar(cliente, headers, modelo["id_modelo"])).json()

    assert corpo["retoma_em"] is None


async def test_esperas_ignora_job_com_hora_no_passado(sessao):
    job = await montar_job(sessao)
    job.disponivel_em = datetime.now(UTC) - timedelta(minutes=5)
    await sessao.commit()

    assert await esperas(sessao, [job.id_execucao]) == {}
    assert await anexar_espera(sessao, []) == []


async def test_painel_mostra_o_consumo_do_dia(cliente, sessao):
    headers = await autenticar(cliente, "cota3@exemplo.com")
    await cota.registrar_uso(sessao, 1, 120)

    corpo = (await cliente.get("/api/v1/painel", headers=headers)).json()

    assert corpo["cota_youtube"]["unidades_usadas"] == 120
    assert corpo["cota_youtube"]["unidades_limite"] == 10000
    assert corpo["cota_youtube"]["renova_em"]


# --------------------------------------------------------------------------- visão do admin

ROTA_ADMIN_COTA = "/api/v1/admin/cota-youtube"


async def autenticar_admin(cliente, sessao, email: str) -> dict:
    headers = await autenticar(cliente, email)
    usuario = await sessao.scalar(select(Usuario).where(Usuario.email == email))
    usuario.papel = "admin"
    await sessao.commit()
    return headers


async def test_cota_por_empresa_e_so_para_admin(cliente):
    headers = await autenticar(cliente, "pme@exemplo.com")

    assert (await cliente.get(ROTA_ADMIN_COTA, headers=headers)).status_code == 403
    assert (await cliente.get(ROTA_ADMIN_COTA)).status_code == 401


async def test_admin_ve_o_dia_por_empresa(cliente, sessao):
    headers = await autenticar_admin(cliente, sessao, "admin@exemplo.com")
    grande = Empresa(nome="Loja Grande")
    pequena = Empresa(nome="Loja Pequena")
    sessao.add_all([grande, pequena])
    await sessao.commit()
    await cota.registrar_uso(sessao, grande.id_empresa, 2500)
    await cota.registrar_uso(sessao, pequena.id_empresa, 40)
    await cota.registrar_uso(sessao, pequena.id_empresa, 60, datetime.now(UTC) - timedelta(days=3))
    await cota.registrar_uso(sessao, ID_AJUSTE, 100)

    corpo = (await cliente.get(ROTA_ADMIN_COTA, headers=headers)).json()

    assert corpo["usado_hoje"] == 2640
    assert corpo["ajuste_hoje"] == 100
    assert corpo["limite"] == 10000
    assert corpo["teto_folga"] == 7000
    nomes = [e["nome"] for e in corpo["empresas"]]
    assert nomes == ["Loja Grande", "Loja Pequena"]  # o ajuste não é empresa
    primeira, segunda = corpo["empresas"]
    assert primeira["acima_da_fatia"] is True
    assert segunda["unidades_hoje"] == 40
    assert segunda["unidades_periodo"] == 100
    assert segunda["acima_da_fatia"] is False


async def test_historico_tem_um_ponto_por_dia_com_zero_nos_vazios(cliente, sessao):
    headers = await autenticar_admin(cliente, sessao, "admin2@exemplo.com")
    await cota.registrar_uso(sessao, 7, 300, datetime.now(UTC) - timedelta(days=2))
    await cota.registrar_uso(sessao, 7, 100)

    corpo = (await cliente.get(f"{ROTA_ADMIN_COTA}?dias=7", headers=headers)).json()

    assert len(corpo["historico"]) == 7
    assert [p["unidades"] for p in corpo["historico"]][-3:] == [300, 0, 100]
    assert corpo["pico_no_periodo"] == 300
    assert corpo["media_no_periodo"] == round(400 / 7, 1)
    # Empresa que não existe mais continua na conta: a API já cobrou.
    assert corpo["empresas"][0]["nome"] == "Empresa excluída (#7)"


async def test_admin_ve_quem_esta_esperando_a_cota(cliente, sessao):
    headers = await autenticar_admin(cliente, sessao, "admin3@exemplo.com")
    job = await montar_job(sessao)
    id_empresa = await empresa_do(sessao, job)
    await fila.adiar(sessao, job, datetime.now(UTC) + timedelta(hours=2), cota.MOTIVO_COTA)

    corpo = (await cliente.get(ROTA_ADMIN_COTA, headers=headers)).json()

    linha = next(e for e in corpo["empresas"] if e["id_empresa"] == id_empresa)
    assert linha["execucoes_aguardando"] == 1


@pytest.mark.parametrize("dias", [0, 36])
async def test_periodo_fora_do_historico_e_recusado(cliente, sessao, dias):
    headers = await autenticar_admin(cliente, sessao, f"admin-d{dias}@exemplo.com")

    resposta = await cliente.get(f"{ROTA_ADMIN_COTA}?dias={dias}", headers=headers)

    assert resposta.status_code == 422
