"""Worker de tópicos: consome jobs tipo 'topicos' e popula TEMAS e COMENTARIO_TEMA.

Roda no MESMO processo do runner, como a coleta e a inferência. É a última etapa
da cadeia (`workers/pipeline.py`): é ela que encerra a execução.

**Transporte, não método.** Aqui se lê comentário, se grava tema e se trata
falha; o que decide quais assuntos existem é `app/topicos/`. A troca de NMF por
LDA, se algum dia acontecer, não toca neste arquivo.

**Entra o texto ORIGINAL.** Diferente do worker de inferência, que aplica
`preparar_texto` porque o BERTimbau precisa dele: aqui a limpeza é outra
(`app/topicos/texto.py`), e converter emoji em palavra faria "risos" e "coração"
concorrerem a tema. O banco guarda o original e é dele que se parte.

**Idempotente.** Execução que já tem tema não é reprocessada: `TEMAS` é o
registro daquela modelagem, e rodar de novo ou duplicaria as linhas ou mudaria os
temas debaixo de um painel que já foi lido. Para refazer de verdade, apague os
temas da execução e enfileire outro job — o caminho é explícito de propósito.

**Execução sem tema é resultado, não erro.** Abaixo do mínimo de comentários, ou
com vocabulário pobre demais, a execução conclui normalmente com zero temas e o
motivo vai para o log com o `id_execucao`.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comentario import Comentario
from app.models.comentario_tema import ComentarioTema
from app.models.job import Job
from app.models.tema import Tema
from app.models.video import Video
from app.topicos.modelo import ResultadoTopicos, modelar, representante_do_tema
from app.workers import fila

logger = logging.getLogger(__name__)

TIPO_JOB = "topicos"


class FalhaTopicos(Exception):
    """Falha que encerra o job: vai para a DLQ e marca a execução como 'erro'."""


async def _ja_tem_temas(db: AsyncSession, id_execucao: int) -> bool:
    total = await db.scalar(
        select(func.count()).select_from(Tema).where(Tema.id_execucao == id_execucao)
    )
    return bool(total)


async def _comentarios(db: AsyncSession, id_execucao: int) -> list[tuple[int, str]]:
    """`(id_comentario, texto ORIGINAL)` da execução, em ordem estável.

    A ordem importa para o determinismo: o NMF recebe a matriz na ordem em que os
    documentos chegam, e uma ordem diferente daria uma fatoração diferente mesmo
    com a mesma semente.
    """
    linhas = await db.execute(
        select(Comentario.id_comentario, Comentario.texto)
        .join(Video, Video.id_video == Comentario.id_video)
        .where(Video.id_execucao == id_execucao)
        .order_by(Comentario.id_comentario)
    )
    return [(id_comentario, texto) for id_comentario, texto in linhas]


async def _gravar(db: AsyncSession, id_execucao: int, resultado: ResultadoTopicos) -> int:
    """Grava TEMAS e COMENTARIO_TEMA numa transação. Devolve quantos temas gravou."""
    indice_para_id: dict[int, int] = {}

    for tema in resultado.temas:
        linha = Tema(
            id_execucao=id_execucao,
            rotulo_tema=tema.rotulo,
            palavras_chave=list(tema.palavras_chave),
        )
        db.add(linha)
        # flush para o banco atribuir o id_tema que COMENTARIO_TEMA referencia.
        await db.flush()
        indice_para_id[tema.indice] = linha.id_tema

    for atribuicao in resultado.atribuicoes:
        db.add(
            ComentarioTema(
                id_comentario=atribuicao.id_comentario,
                id_tema=indice_para_id[atribuicao.indice_tema],
                peso=atribuicao.peso,
            )
        )

    # Um commit só: ou a execução tem a modelagem inteira, ou não tem nenhuma.
    # Meia modelagem no painel seria pior que nenhuma.
    await db.commit()
    return len(resultado.temas)


async def processar(db: AsyncSession, job: Job) -> int:
    """Modela os tópicos da execução. Devolve quantos temas gravou."""
    id_execucao = job.id_execucao

    if await _ja_tem_temas(db, id_execucao):
        logger.info("topicos ja existem, nada a fazer id_execucao=%s (idempotencia)", id_execucao)
        return 0

    comentarios = await _comentarios(db, id_execucao)
    logger.info("topicos iniciados id_execucao=%s comentarios=%s", id_execucao, len(comentarios))

    resultado = modelar(comentarios)

    if not resultado.houve_temas:
        # Resultado válido: a execução conclui sem tema e o motivo fica no log.
        logger.info("topicos nao gerados id_execucao=%s motivo=%s", id_execucao, resultado.motivo)
        return 0

    gravados = await _gravar(db, id_execucao, resultado)

    textos = dict(comentarios)
    for tema in resultado.temas:
        representante = representante_do_tema(tema.indice, resultado.atribuicoes, textos)
        quantos = sum(1 for a in resultado.atribuicoes if a.indice_tema == tema.indice)
        logger.info(
            "tema id_execucao=%s rotulo=%r comentarios=%s representativo=%s",
            id_execucao,
            tema.rotulo,
            quantos,
            representante,
        )

    sem_tema = len(comentarios) - len({a.id_comentario for a in resultado.atribuicoes})
    logger.info(
        "topicos finalizados id_execucao=%s temas=%s ligacoes=%s comentarios_sem_tema=%s",
        id_execucao,
        gravados,
        len(resultado.atribuicoes),
        sem_tema,
    )
    return gravados


async def executar_proximo(db: AsyncSession) -> bool:
    """Reivindica e processa um job. `False` quando não havia nada na fila."""
    job = await fila.reivindicar(db, TIPO_JOB)
    if job is None:
        return False

    try:
        await processar(db, job)
    except FalhaTopicos as erro:
        await _descartar(db, job)
        await fila.enviar_para_dlq(db, job, str(erro))
        return True
    except Exception as erro:
        # Rede de segurança: nenhum job pode ficar preso em 'processando'.
        await _descartar(db, job)
        logger.exception("falha inesperada nos topicos id_execucao=%s", job.id_execucao)
        await fila.enviar_para_dlq(db, job, f"erro inesperado: {erro!r}")
        return True

    await fila.concluir(db, job)
    return True


async def _descartar(db: AsyncSession, job: Job) -> None:
    """Desfaz o que não foi commitado e recarrega o job.

    O rollback expira os objetos da sessão; sem o refresh, ler `job.tipo` para
    montar a linha da DLQ dispararia um carregamento preguiçoso fora do contexto
    assíncrono do SQLAlchemy.
    """
    await db.rollback()
    await db.refresh(job)
