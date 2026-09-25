"""Testes do reaper: job que o worker abandonou volta à fila, e não em laço.

O cenário que estes testes reproduzem é o de produção: o processo morre no meio
de um job (deploy, OOM, queda), o job fica em `processando` e ninguém mais o
reivindica. Simular a morte é simples — reivindicar e não concluir.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import hash_token
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario
from app.workers import fila

LIMITE_MINUTOS = 15
MAX_TENTATIVAS = 4


async def montar_job(sessao, *, email: str, tipo: str = "coleta") -> Job:
    usuario = Usuario(nome="Dona", email=email, senha_hash=hash_token("x"), papel="usuario_pme")
    sessao.add(usuario)
    await sessao.flush()
    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario, nome="Campanha", termo_pesquisa="x", filtros={}
    )
    sessao.add(modelo)
    await sessao.flush()
    execucao = Execucao(id_modelo=modelo.id_modelo, status="pendente")
    sessao.add(execucao)
    await sessao.flush()
    job = Job(tipo=tipo, id_execucao=execucao.id_execucao, status="pendente")
    sessao.add(job)
    await sessao.commit()
    await sessao.refresh(job)
    return job


async def envelhecer(sessao, job: Job, minutos: int) -> None:
    """Empurra a reivindicação para trás no tempo, simulando o worker morto."""
    job.reivindicado_em = datetime.now(UTC) - timedelta(minutes=minutos)
    await sessao.commit()


# --------------------------------------------------------------------------- reivindicação


async def test_reivindicar_marca_a_hora(sessao):
    """Sem esta marca o reaper não sabe distinguir "rodando" de "abandonado"."""
    await montar_job(sessao, email="r1@exemplo.com")

    job = await fila.reivindicar(sessao, "coleta")

    assert job.reivindicado_em is not None


async def test_job_pendente_nao_tem_hora_de_reivindicacao(sessao):
    job = await montar_job(sessao, email="r2@exemplo.com")

    assert job.reivindicado_em is None


# --------------------------------------------------------------------------- devolução


async def test_job_preso_volta_para_a_fila(sessao):
    job = await montar_job(sessao, email="r3@exemplo.com")
    await fila.reivindicar(sessao, "coleta")
    await envelhecer(sessao, job, LIMITE_MINUTOS + 1)

    tratados = await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS)

    assert tratados == 1
    await sessao.refresh(job)
    assert job.status == "pendente"
    assert job.reivindicado_em is None
    assert job.tentativas == 1


async def test_job_devolvido_pode_ser_reivindicado_de_novo(sessao):
    """O ponto do reaper: a execução volta a andar."""
    job = await montar_job(sessao, email="r4@exemplo.com")
    await fila.reivindicar(sessao, "coleta")
    await envelhecer(sessao, job, LIMITE_MINUTOS + 1)
    await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS)

    de_novo = await fila.reivindicar(sessao, "coleta")

    assert de_novo is not None
    assert de_novo.id_job == job.id_job


async def test_job_dentro_do_limite_nao_e_tocado(sessao):
    """Devolver job que só está demorando faria dois workers na mesma execução."""
    job = await montar_job(sessao, email="r5@exemplo.com")
    await fila.reivindicar(sessao, "coleta")
    await envelhecer(sessao, job, LIMITE_MINUTOS - 1)

    assert await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS) == 0

    await sessao.refresh(job)
    assert job.status == "processando"
    assert job.tentativas == 0


async def test_job_pendente_nao_e_devolvido(sessao):
    await montar_job(sessao, email="r6@exemplo.com")

    assert await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS) == 0


async def test_fila_vazia_nao_quebra(sessao):
    assert await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS) == 0


# --------------------------------------------------------------------------- laço infinito


async def test_job_que_mata_o_worker_acaba_na_dlq(sessao):
    """O requisito central: contar tentativa é o que impede o laço.

    Um job que derruba o worker por conta própria seria devolvido, mataria o
    worker de novo, e assim para sempre. Com a contagem ele chega à DLQ e a
    execução termina em `erro` — resposta ruim, mas resposta.
    """
    job = await montar_job(sessao, email="r7@exemplo.com")
    id_job, id_execucao = job.id_job, job.id_execucao

    for _ in range(MAX_TENTATIVAS + 1):
        reivindicado = await fila.reivindicar(sessao, "coleta")
        if reivindicado is None:
            break  # ja foi para a DLQ
        await envelhecer(sessao, reivindicado, LIMITE_MINUTOS + 1)
        await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS)

    # Saiu da fila e esta arquivado.
    assert await sessao.get(Job, id_job) is None
    morto = await sessao.scalar(select(JobDlq))
    assert morto.id_job == id_job
    assert "abandonado" in morto.erro

    execucao = await sessao.get(Execucao, id_execucao)
    assert execucao.status == "erro"


async def test_devolve_ate_o_limite_e_so_entao_arquiva(sessao):
    job = await montar_job(sessao, email="r8@exemplo.com")

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        await fila.reivindicar(sessao, "coleta")
        atual = await sessao.get(Job, job.id_job)
        await envelhecer(sessao, atual, LIMITE_MINUTOS + 1)
        await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS)

        atual = await sessao.get(Job, job.id_job)
        assert atual is not None, f"arquivou cedo demais na tentativa {tentativa}"
        assert atual.tentativas == tentativa

    # A proxima passagem estoura o limite.
    await fila.reivindicar(sessao, "coleta")
    atual = await sessao.get(Job, job.id_job)
    await envelhecer(sessao, atual, LIMITE_MINUTOS + 1)
    await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS)

    assert await sessao.get(Job, job.id_job) is None


# --------------------------------------------------------------------------- linha antiga


async def test_job_sem_reivindicado_em_usa_criado_em(sessao):
    """Linha anterior à migration 0009: `criado_em` é o piso seguro."""
    job = await montar_job(sessao, email="r9@exemplo.com")
    await fila.reivindicar(sessao, "coleta")
    # Simula a linha antiga: em 'processando' e sem a hora da reivindicação.
    job.reivindicado_em = None
    job.criado_em = datetime.now(UTC) - timedelta(minutes=LIMITE_MINUTOS + 5)
    await sessao.commit()

    assert await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS) == 1

    await sessao.refresh(job)
    assert job.status == "pendente"


@pytest.mark.parametrize("tipo", ["coleta", "inferencia", "topicos"])
async def test_reaper_cobre_as_tres_etapas(sessao, tipo):
    job = await montar_job(sessao, email=f"r10{tipo}@exemplo.com", tipo=tipo)
    await fila.reivindicar(sessao, tipo)
    await envelhecer(sessao, job, LIMITE_MINUTOS + 1)

    assert await fila.devolver_presos(sessao, LIMITE_MINUTOS, MAX_TENTATIVAS) == 1
