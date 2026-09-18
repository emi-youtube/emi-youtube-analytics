"""Consumo da tabela `jobs` — a fila do projeto (CLAUDE.md Seção 5).

`SELECT ... FOR UPDATE SKIP LOCKED` é o que permite rodar mais de um worker sem
serviço de fila: quem chega primeiro tranca a linha, os outros pulam para a
próxima em vez de esperar.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq

logger = logging.getLogger(__name__)

STATUS_PENDENTE = "pendente"
STATUS_PROCESSANDO = "processando"
STATUS_CONCLUIDA = "concluida"
STATUS_ERRO = "erro"

# Texto do erro guardado na DLQ; o suficiente para depurar sem estourar a coluna.
MAX_ERRO_DLQ = 2000


async def reivindicar(db: AsyncSession, tipo: str) -> Job | None:
    """Tranca e assume um job pendente do tipo pedido. `None` se a fila está vazia.

    A execução vai junto para 'processando': é o que o usuário vê no GET /execucoes
    enquanto a coleta acontece (UC04).
    """
    job = await db.scalar(
        select(Job)
        .where(Job.tipo == tipo, Job.status == STATUS_PENDENTE)
        .order_by(Job.criado_em, Job.id_job)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None

    job.status = STATUS_PROCESSANDO

    execucao = await db.get(Execucao, job.id_execucao)
    if execucao is not None:
        execucao.status = STATUS_PROCESSANDO
        execucao.iniciado_em = datetime.now(UTC)

    await db.commit()
    await db.refresh(job)

    logger.info(
        "job reivindicado id_job=%s tipo=%s id_execucao=%s", job.id_job, job.tipo, job.id_execucao
    )
    return job


async def registrar_tentativa(db: AsyncSession, job: Job) -> int:
    """Grava mais uma tentativa malsucedida e devolve o total.

    Persistido a cada falha (e não só no fim) para que o número sobreviva a uma
    queda do worker no meio do job.
    """
    job.tentativas += 1
    await db.commit()
    return job.tentativas


async def concluir(db: AsyncSession, job: Job) -> None:
    job.status = STATUS_CONCLUIDA

    execucao = await db.get(Execucao, job.id_execucao)
    if execucao is not None:
        execucao.status = STATUS_CONCLUIDA
        execucao.concluido_em = datetime.now(UTC)

    await db.commit()
    logger.info("job concluido id_job=%s id_execucao=%s", job.id_job, job.id_execucao)


async def enviar_para_dlq(db: AsyncSession, job: Job, erro: str) -> None:
    """Arquiva o job na DLQ, tira da fila e marca a execução como 'erro'.

    O job sai de `jobs` para não ser reivindicado de novo; o histórico fica em
    `jobs_dlq`, que preserva o id original.
    """
    id_job = job.id_job
    id_execucao = job.id_execucao

    db.add(
        JobDlq(
            id_job=id_job,
            tipo=job.tipo,
            id_execucao=id_execucao,
            erro=erro[:MAX_ERRO_DLQ],
        )
    )
    await db.delete(job)

    execucao = await db.get(Execucao, id_execucao)
    if execucao is not None:
        execucao.status = STATUS_ERRO
        execucao.concluido_em = datetime.now(UTC)

    await db.commit()
    logger.error(
        "job enviado para a DLQ id_job=%s id_execucao=%s erro=%s", id_job, id_execucao, erro
    )
