"""Testes da execução de análise: disparo (UC03) e acompanhamento (UC04).

O que importa aqui, além do caminho feliz: a requisição NÃO pode coletar nada
(só enfileirar), execução de outro usuário responde 404, e o mesmo modelo não
pode ter duas execuções ativas.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.execucao import Execucao
from app.models.job import Job
from app.services.execucao import STATUS_PENDENTE, TIPO_JOB_COLETA

from .conftest import autenticar

ROTA = "/api/v1/execucoes"
ROTA_MODELOS = "/api/v1/modelos-analise"

DONO = "dona@exemplo.com"
INTRUSO = "intruso@exemplo.com"


async def criar_modelo(cliente: AsyncClient, headers: dict, **campos) -> dict:
    corpo = {
        "nome": "Campanha de verão",
        "termo_pesquisa": "tênis esportivo",
        # UC02 exige ao menos um vídeo para o modelo ter escopo.
        "filtros": {"videos": ["dQw4w9WgXcQ"]},
        **campos,
    }
    return (await cliente.post(ROTA_MODELOS, json=corpo, headers=headers)).json()


async def disparar(cliente: AsyncClient, headers: dict, id_modelo: int):
    return await cliente.post(ROTA, json={"id_modelo": id_modelo}, headers=headers)


# --------------------------------------------------------------------------- autenticação


@pytest.mark.parametrize(
    ("metodo", "caminho"),
    [("post", ROTA), ("get", ROTA), ("get", f"{ROTA}/1")],
)
async def test_todas_as_rotas_exigem_autenticacao(cliente, metodo, caminho):
    resposta = await cliente.request(metodo, caminho, json={})

    assert resposta.status_code == 401


# --------------------------------------------------------------------------- criação


async def test_disparar_responde_202_com_id_execucao(cliente):
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)

    resposta = await disparar(cliente, headers, modelo["id_modelo"])

    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["id_execucao"]
    assert corpo["id_modelo"] == modelo["id_modelo"]
    assert corpo["status"] == STATUS_PENDENTE


async def test_execucao_nasce_pendente_e_sem_datas(cliente, sessao):
    """A requisição enfileira e sai: quem preenche iniciado_em/concluido_em é o worker."""
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)

    corpo = (await disparar(cliente, headers, modelo["id_modelo"])).json()

    execucao = await sessao.get(Execucao, corpo["id_execucao"])
    assert execucao.status == STATUS_PENDENTE
    assert execucao.iniciado_em is None
    assert execucao.concluido_em is None


async def test_disparar_publica_job_de_coleta_pendente(cliente, sessao):
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)

    corpo = (await disparar(cliente, headers, modelo["id_modelo"])).json()

    jobs = (await sessao.scalars(select(Job))).all()
    assert len(jobs) == 1
    assert jobs[0].tipo == TIPO_JOB_COLETA
    assert jobs[0].status == STATUS_PENDENTE
    assert jobs[0].id_execucao == corpo["id_execucao"]
    assert jobs[0].tentativas == 0


async def test_job_congela_os_parametros_do_modelo(cliente, sessao):
    """Editar o modelo depois do disparo não pode mudar a coleta já enfileirada."""
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)
    await disparar(cliente, headers, modelo["id_modelo"])

    await cliente.patch(
        f"{ROTA_MODELOS}/{modelo['id_modelo']}",
        json={"termo_pesquisa": "outro termo"},
        headers=headers,
    )

    job = await sessao.scalar(select(Job))
    assert job.payload["termo_pesquisa"] == "tênis esportivo"
    assert job.payload["id_modelo"] == modelo["id_modelo"]


async def test_modelo_inexistente_retorna_404(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await disparar(cliente, headers, 9999)

    assert resposta.status_code == 404


async def test_modelo_de_outro_usuario_retorna_404_e_nao_enfileira(cliente, sessao):
    """404 e não 403: um 403 confirmaria que o id existe."""
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    modelo = await criar_modelo(cliente, headers_dono)

    resposta = await disparar(cliente, headers_intruso, modelo["id_modelo"])

    assert resposta.status_code == 404
    assert (await sessao.scalars(select(Job))).all() == []
    assert (await sessao.scalars(select(Execucao))).all() == []


# --------------------------------------------------------------------------- execução única


async def test_segundo_disparo_do_mesmo_modelo_retorna_409(cliente):
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)
    await disparar(cliente, headers, modelo["id_modelo"])

    resposta = await disparar(cliente, headers, modelo["id_modelo"])

    assert resposta.status_code == 409


async def test_disparo_recusado_nao_deixa_execucao_nem_job_extra(cliente, sessao):
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)
    await disparar(cliente, headers, modelo["id_modelo"])

    await disparar(cliente, headers, modelo["id_modelo"])

    assert len((await sessao.scalars(select(Execucao))).all()) == 1
    assert len((await sessao.scalars(select(Job))).all()) == 1


@pytest.mark.parametrize("status_anterior", ["concluida", "erro"])
async def test_disparo_liberado_apos_execucao_terminar(cliente, sessao, status_anterior):
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)
    primeira = (await disparar(cliente, headers, modelo["id_modelo"])).json()

    execucao = await sessao.get(Execucao, primeira["id_execucao"])
    execucao.status = status_anterior
    await sessao.commit()

    resposta = await disparar(cliente, headers, modelo["id_modelo"])

    assert resposta.status_code == 202


async def test_modelos_diferentes_executam_em_paralelo(cliente):
    """O limite é por modelo, não por usuário."""
    headers = await autenticar(cliente, DONO)
    primeiro = await criar_modelo(cliente, headers)
    segundo = await criar_modelo(cliente, headers, nome="Campanha de inverno")

    assert (await disparar(cliente, headers, primeiro["id_modelo"])).status_code == 202
    assert (await disparar(cliente, headers, segundo["id_modelo"])).status_code == 202


async def test_indice_barra_execucao_ativa_duplicada_no_banco(cliente, sessao):
    """A regra não depende só da verificação no serviço: o banco recusa a segunda linha."""
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)
    await disparar(cliente, headers, modelo["id_modelo"])

    sessao.add(Execucao(id_modelo=modelo["id_modelo"], status=STATUS_PENDENTE))
    with pytest.raises(IntegrityError):
        await sessao.commit()
    await sessao.rollback()


# --------------------------------------------------------------------------- consulta


async def test_detalhar_execucao_do_proprio_usuario(cliente):
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)
    criada = (await disparar(cliente, headers, modelo["id_modelo"])).json()

    resposta = await cliente.get(f"{ROTA}/{criada['id_execucao']}", headers=headers)

    assert resposta.status_code == 200
    assert resposta.json()["id_execucao"] == criada["id_execucao"]
    assert resposta.json()["status"] == STATUS_PENDENTE


async def test_detalhar_execucao_de_outro_usuario_retorna_404(cliente):
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    modelo = await criar_modelo(cliente, headers_dono)
    criada = (await disparar(cliente, headers_dono, modelo["id_modelo"])).json()

    resposta = await cliente.get(f"{ROTA}/{criada['id_execucao']}", headers=headers_intruso)

    assert resposta.status_code == 404


async def test_detalhar_execucao_inexistente_retorna_404(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await cliente.get(f"{ROTA}/9999", headers=headers)

    assert resposta.status_code == 404


async def test_detalhar_reflete_o_andamento_do_worker(cliente, sessao):
    """UC04: é por aqui que o usuário acompanha a execução."""
    headers = await autenticar(cliente, DONO)
    modelo = await criar_modelo(cliente, headers)
    criada = (await disparar(cliente, headers, modelo["id_modelo"])).json()

    execucao = await sessao.get(Execucao, criada["id_execucao"])
    execucao.status = "processando"
    await sessao.commit()

    resposta = await cliente.get(f"{ROTA}/{criada['id_execucao']}", headers=headers)

    assert resposta.json()["status"] == "processando"


async def test_listar_traz_so_as_execucoes_do_usuario(cliente):
    headers_dono = await autenticar(cliente, DONO)
    headers_intruso = await autenticar(cliente, INTRUSO)
    modelo_dono = await criar_modelo(cliente, headers_dono)
    modelo_intruso = await criar_modelo(cliente, headers_intruso)
    await disparar(cliente, headers_dono, modelo_dono["id_modelo"])
    await disparar(cliente, headers_intruso, modelo_intruso["id_modelo"])

    resposta = await cliente.get(ROTA, headers=headers_dono)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["id_modelo"] == modelo_dono["id_modelo"]


async def test_listar_sem_execucoes_devolve_lista_vazia(cliente):
    headers = await autenticar(cliente, DONO)

    resposta = await cliente.get(ROTA, headers=headers)

    assert resposta.status_code == 200
    assert resposta.json() == []


async def test_listar_traz_a_mais_recente_primeiro(cliente):
    headers = await autenticar(cliente, DONO)
    primeiro = await criar_modelo(cliente, headers)
    segundo = await criar_modelo(cliente, headers, nome="Campanha de inverno")
    antiga = (await disparar(cliente, headers, primeiro["id_modelo"])).json()
    recente = (await disparar(cliente, headers, segundo["id_modelo"])).json()

    corpo = (await cliente.get(ROTA, headers=headers)).json()

    assert [e["id_execucao"] for e in corpo] == [recente["id_execucao"], antiga["id_execucao"]]
