"""Consumo da tabela `jobs` — a fila do projeto (CLAUDE.md Seção 5).

`SELECT ... FOR UPDATE SKIP LOCKED` é o que permite rodar mais de um worker sem
serviço de fila: quem chega primeiro tranca a linha, os outros pulam para a
próxima em vez de esperar.

**Job preso.** Se o worker morre no meio de um job (queda, deploy, OOM), o job
fica em `processando` para sempre — o SELECT acima só busca `pendente`, então
ninguém mais o reivindica e a execução trava sem resultado e sem erro. Quem
resolve é `devolver_presos`, chamado pelo laço do runner.

Este módulo é agnóstico de etapa: ele reivindica, conta tentativa, conclui e arquiva
na DLQ, sem saber o que cada tipo de job faz. Quem sabe a ORDEM das etapas é
`workers/pipeline.py`, e `concluir` consulta esse mapa para publicar a seguinte.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.workers import pipeline

logger = logging.getLogger(__name__)

# Só os tipos que têm worker podem ser devolvidos à fila. Um `topicos`
# enfileirado à mão antes de o worker existir ficaria em `processando`... não
# ficaria: ele nunca é reivindicado. Mas a lista deixa a intenção explícita e
# impede que um tipo futuro sem consumidor entre em laço de devolução.
TIPOS_COM_WORKER = ("coleta", "inferencia", "topicos")

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
    # Marca a hora da reivindicação: é por ela que o reaper reconhece o job que
    # um worker morto deixou para trás.
    job.reivindicado_em = datetime.now(UTC)

    execucao = await db.get(Execucao, job.id_execucao)
    if execucao is not None:
        execucao.status = STATUS_PROCESSANDO
        if execucao.iniciado_em is None:
            # Só na PRIMEIRA etapa. Uma execução passa por vários jobs (coleta ->
            # inferência), e sobrescrever aqui faria o início da execução voltar no
            # tempo a cada etapa: a duração que o painel mostra mediria só a última.
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


async def concluir(db: AsyncSession, job: Job) -> Job | None:
    """Encerra a etapa e passa a execução adiante. Devolve o job publicado, se houver.

    Uma única transação faz as três coisas: marca este job concluído, publica o job da
    etapa seguinte e decide o status da execução. Atomicidade é o ponto — job concluído
    sem o próximo publicado deixaria a execução em `processando` sem nada na fila, e
    ninguém viria buscá-la (ver `workers/pipeline.py`).

    A execução só vira `concluida` quando a cadeia termina. Enquanto houver etapa
    pendente ela continua `processando`, porque é o que ela é: a coleta acabou, a
    análise não.
    """
    job.status = STATUS_CONCLUIDA

    tipo_seguinte = pipeline.proxima_etapa(job.tipo)
    proximo: Job | None = None
    if tipo_seguinte is not None:
        proximo = Job(
            tipo=tipo_seguinte,
            id_execucao=job.id_execucao,
            status=STATUS_PENDENTE,
            # Sem payload: a etapa seguinte encontra tudo de que precisa pelo
            # `id_execucao` (os comentários já estão no banco). O payload congelado do
            # disparo existe para a coleta, que fala com uma API externa e não pode
            # reler MODELOS_ANALISE no meio do caminho.
        )
        db.add(proximo)

    if tipo_seguinte is None:
        # Fim da cadeia: agora sim a execução está pronta. Com etapa pendente ela
        # continua `processando` e não há nada a atualizar nela.
        execucao = await db.get(Execucao, job.id_execucao)
        if execucao is not None:
            execucao.status = STATUS_CONCLUIDA
            execucao.concluido_em = datetime.now(UTC)

    await db.commit()

    if proximo is None:
        logger.info(
            "job concluido, execucao encerrada id_job=%s tipo=%s id_execucao=%s",
            job.id_job,
            job.tipo,
            job.id_execucao,
        )
        return None

    await db.refresh(proximo)
    logger.info(
        "job concluido, etapa seguinte publicada id_job=%s tipo=%s id_execucao=%s "
        "proximo_job=%s proximo_tipo=%s",
        job.id_job,
        job.tipo,
        job.id_execucao,
        proximo.id_job,
        proximo.tipo,
    )
    return proximo


async def devolver_presos(db: AsyncSession, limite_minutos: int, max_tentativas: int) -> int:
    """Devolve à fila os jobs que um worker abandonou. Retorna quantos tratou.

    **O problema.** `reivindicar` põe o job em `processando` e é o worker que o
    conclui. Se o processo morre antes disso — deploy, OOM, queda —, ninguém
    mais toca naquele job: a consulta da fila só enxerga `pendente`. A execução
    fica `processando` para sempre, e o usuário não recebe nem resultado nem
    erro.

    **A regra.** Job em `processando` cuja reivindicação é mais velha que
    `limite_minutos` conta mais uma TENTATIVA e:

    - volta para `pendente`, se ainda tem tentativa sobrando;
    - vai para a DLQ, se esgotou.

    Contar tentativa é o que impede o laço infinito. Um job que derruba o worker
    por conta própria — um comentário que estoura a memória, por exemplo — seria
    devolvido, mataria o worker de novo e assim por diante para sempre. Com a
    contagem ele chega à DLQ e a execução termina em `erro`, que é uma resposta
    ruim mas é uma resposta.

    **O limite tem de ser bem maior que o job mais lento.** Devolver um job que
    só está demorando faz dois workers processarem a mesma execução ao mesmo
    tempo. O padrão (`worker_timeout_job_minutos`) é 15 minutos, contra coletas
    que levam segundos no escopo do projeto.

    **`SKIP LOCKED` aqui também:** com mais de um worker, dois reapers rodam ao
    mesmo tempo e não podem tratar o mesmo job duas vezes.

    Reprocessar é seguro porque os três workers são idempotentes ou atômicos: a
    coleta só commita no fim (morrer no meio não deixa vídeo pela metade), a
    inferência pula comentário que já tem análise, e os tópicos verificam se a
    execução já tem tema.
    """
    limite = datetime.now(UTC) - timedelta(minutes=limite_minutos)

    presos = list(
        (
            await db.scalars(
                select(Job)
                .where(
                    Job.tipo.in_(TIPOS_COM_WORKER),
                    Job.status == STATUS_PROCESSANDO,
                    # Linha anterior à migration 0009 não tem `reivindicado_em`;
                    # `criado_em` é sempre anterior, então serve de piso seguro.
                    func.coalesce(Job.reivindicado_em, Job.criado_em) < limite,
                )
                .order_by(Job.id_job)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if not presos:
        return 0

    for job in presos:
        job.tentativas += 1
        if job.tentativas > max_tentativas:
            logger.error(
                "job preso esgotou as tentativas, vai para a DLQ id_job=%s tipo=%s "
                "id_execucao=%s tentativas=%s",
                job.id_job,
                job.tipo,
                job.id_execucao,
                job.tentativas,
            )
            await enviar_para_dlq(
                db,
                job,
                f"job abandonado por worker morto e devolvido {job.tentativas} vez(es); "
                f"esgotou o limite de {max_tentativas} tentativas",
            )
            continue

        job.status = STATUS_PENDENTE
        job.reivindicado_em = None
        logger.warning(
            "job preso devolvido a fila id_job=%s tipo=%s id_execucao=%s tentativa=%s",
            job.id_job,
            job.tipo,
            job.id_execucao,
            job.tentativas,
        )

    await db.commit()
    return len(presos)


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
