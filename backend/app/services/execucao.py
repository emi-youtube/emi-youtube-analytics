"""Regras da execução de análise (UC03: disparar; UC04: acompanhar).

Segurança (Seção 4.3.1): a execução não guarda empresa nem usuário — a dona é a
empresa dona do modelo. Toda leitura por id passa por `get_owned`, que faz join com
MODELOS_ANALISE filtrando pela empresa do token (`escopo.da_empresa`, ADR-011) e
responde 404 quando a execução é de outra; um 403 confirmaria que aquele id existe.

Regra do CLAUDE.md: aqui NADA de coleta acontece. O endpoint só enfileira e
responde 202 — a coleta roda no worker, fora do ciclo da requisição.
"""

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execucao import Execucao
from app.models.job import Job
from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario
from app.schemas.execucao import ExecucaoCreate
from app.services import escopo
from app.services.modelo_analise import get_owned as get_modelo_owned

logger = logging.getLogger(__name__)

STATUS_PENDENTE = "pendente"
STATUS_PROCESSANDO = "processando"
# UC03 não prevê execuções concorrentes do mesmo modelo: enquanto a execução não
# terminou (concluida/erro), o modelo está ocupado.
STATUS_ATIVOS = (STATUS_PENDENTE, STATUS_PROCESSANDO)

TIPO_JOB_COLETA = "coleta"

EXECUCAO_EM_ANDAMENTO = (
    "Este modelo já possui uma execução em andamento. Aguarde a conclusão antes de disparar outra."
)


async def _execucao_ativa(db: AsyncSession, id_modelo: int) -> Execucao | None:
    return await db.scalar(
        select(Execucao)
        .where(Execucao.id_modelo == id_modelo, Execucao.status.in_(STATUS_ATIVOS))
        .limit(1)
    )


async def create(db: AsyncSession, usuario: Usuario, dados: ExecucaoCreate) -> Execucao:
    """Cria a execução e publica o job de coleta na MESMA transação.

    Atomicidade importa aqui: uma execução gravada sem o job correspondente
    ficaria 'pendente' para sempre, porque nenhum worker viria buscá-la.
    """
    # Reaproveita o único caminho de acesso a modelo por id — o 404 de modelo de
    # outro usuário já vem de lá, sem uma segunda consulta por id neste serviço.
    modelo = await get_modelo_owned(db, usuario, dados.id_modelo)

    if await _execucao_ativa(db, modelo.id_modelo) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EXECUCAO_EM_ANDAMENTO)

    execucao = Execucao(id_modelo=modelo.id_modelo, status=STATUS_PENDENTE)
    db.add(execucao)
    # flush (e não commit) só para o banco atribuir o id_execucao que o job precisa
    # referenciar: a transação continua aberta e as duas linhas nascem juntas.
    await db.flush()

    db.add(
        Job(
            tipo=TIPO_JOB_COLETA,
            id_execucao=execucao.id_execucao,
            status=STATUS_PENDENTE,
            # Congela os parâmetros no instante do disparo: se o modelo for editado
            # com a coleta em andamento, o worker continua com o que foi pedido.
            payload={
                "id_modelo": modelo.id_modelo,
                "termo_pesquisa": modelo.termo_pesquisa,
                "filtros": modelo.filtros,
            },
        )
    )

    try:
        await db.commit()
    except IntegrityError:
        # Corrida com outro POST simultâneo: o índice parcial único de EXECUCOES
        # é quem garante de fato uma execução ativa por modelo.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=EXECUCAO_EM_ANDAMENTO
        ) from None

    await db.refresh(execucao)

    logger.info(
        "execucao criada e job de coleta publicado id_execucao=%s id_modelo=%s id_usuario=%s",
        execucao.id_execucao,
        modelo.id_modelo,
        usuario.id_usuario,
    )
    return execucao


async def get_owned(db: AsyncSession, usuario: Usuario, id_execucao: int) -> Execucao:
    """Único caminho para alcançar uma execução por id. 404 se não for da empresa."""
    execucao = await db.scalar(
        select(Execucao)
        .join(ModeloAnalise, ModeloAnalise.id_modelo == Execucao.id_modelo)
        .where(
            Execucao.id_execucao == id_execucao,
            escopo.da_empresa(usuario),
        )
    )
    if execucao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Execução não encontrada."
        )
    return execucao


async def list_for_user(db: AsyncSession, usuario: Usuario) -> Sequence[Execucao]:
    resultado = await db.scalars(
        select(Execucao)
        .join(ModeloAnalise, ModeloAnalise.id_modelo == Execucao.id_modelo)
        .where(escopo.da_empresa(usuario))
        .order_by(Execucao.id_execucao.desc())
    )
    return resultado.all()


async def esperas(db: AsyncSession, ids_execucao: Iterable[int]) -> dict[int, datetime]:
    """`{id_execucao: hora}` das execuções cujo job espera a cota da YouTube renovar.

    Só entra quem tem job pendente com `disponivel_em` no futuro (ADR-015). O resto é
    execução que está de fato na fila ou rodando.
    """
    ids = list(ids_execucao)
    if not ids:
        return {}
    linhas = await db.execute(
        select(Job.id_execucao, Job.disponivel_em).where(
            Job.id_execucao.in_(ids),
            Job.status == STATUS_PENDENTE,
            Job.disponivel_em.is_not(None),
            Job.disponivel_em > datetime.now(UTC),
        )
    )
    return {id_execucao: hora for id_execucao, hora in linhas}


async def anexar_espera(db: AsyncSession, execucoes: Sequence[Execucao]) -> Sequence[Execucao]:
    """Preenche `retoma_em` nas execuções que esperam a cota. Devolve as mesmas."""
    por_id = await esperas(db, [e.id_execucao for e in execucoes if e.status == STATUS_PENDENTE])
    for execucao in execucoes:
        execucao.retoma_em = por_id.get(execucao.id_execucao)
    return execucoes
