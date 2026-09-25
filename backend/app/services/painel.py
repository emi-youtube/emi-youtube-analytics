"""Monta a tela Início num endpoint só (`GET /api/v1/painel`).

Todas as contagens são `GROUP BY` sobre as execuções DO USUÁRIO: o recorte por
dono é um join com MODELOS_ANALISE filtrando por `id_usuario`, igual ao resto da
API. Um painel que somasse o banco inteiro mostraria número de outra empresa.

Não há laço sobre comentários aqui — o maior laço percorre os modelos do usuário.
"""

import logging
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.execucao import Execucao
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video
from app.schemas.painel import (
    DestaqueExecucao,
    ModeloNoPainel,
    ResumoPainel,
    TotaisUsuario,
)
from app.services.resultado import (
    contagens_por_execucao,
    distribuicao_de,
    versao_modelo_da_execucao,
    versao_para_resposta,
)

logger = logging.getLogger(__name__)

STATUS_CONCLUIDA = "concluida"
STATUS_ERRO = "erro"


async def _execucoes_do_usuario(db: AsyncSession, usuario: Usuario) -> list[Execucao]:
    resultado = await db.scalars(
        select(Execucao)
        .join(ModeloAnalise, ModeloAnalise.id_modelo == Execucao.id_modelo)
        .where(ModeloAnalise.id_usuario == usuario.id_usuario)
        .order_by(Execucao.id_execucao.desc())
    )
    return list(resultado.all())


async def _motivos_de_falha(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    """`{id_execucao: erro}` da DLQ — o "por que falhou" que a linha do modelo mostra."""
    if not ids:
        return {}
    linhas = await db.execute(
        select(JobDlq.id_execucao, JobDlq.erro)
        .where(JobDlq.id_execucao.in_(ids))
        .order_by(JobDlq.falhou_em.desc())
    )
    # A mais recente vence: o dicionário é preenchido na ordem decrescente e só
    # a primeira ocorrência de cada execução é mantida.
    motivos: dict[int, str] = {}
    for id_execucao, erro in linhas:
        motivos.setdefault(id_execucao, erro)
    return motivos


async def resumo(db: AsyncSession, usuario: Usuario) -> ResumoPainel:
    """O painel inteiro do usuário."""
    execucoes = await _execucoes_do_usuario(db, usuario)
    ids = [execucao.id_execucao for execucao in execucoes]
    concluidas = [e for e in execucoes if e.status == STATUS_CONCLUIDA]

    modelos = list(
        (
            await db.scalars(
                select(ModeloAnalise)
                .where(ModeloAnalise.id_usuario == usuario.id_usuario)
                .order_by(ModeloAnalise.id_modelo.desc())
            )
        ).all()
    )

    # --- contagens, todas agrupadas no banco ---
    contagens = await contagens_por_execucao(db, ids)

    totais_video = (
        {
            id_execucao: quantidade
            for id_execucao, quantidade in await db.execute(
                select(Video.id_execucao, func.count())
                .where(Video.id_execucao.in_(ids))
                .group_by(Video.id_execucao)
            )
        }
        if ids
        else {}
    )

    totais_tema = (
        {
            id_execucao: quantidade
            for id_execucao, quantidade in await db.execute(
                select(Tema.id_execucao, func.count())
                .where(Tema.id_execucao.in_(ids))
                .group_by(Tema.id_execucao)
            )
        }
        if ids
        else {}
    )

    analisados_total = (
        await db.scalar(
            select(func.count())
            .select_from(AnaliseSentimento)
            .join(Comentario, Comentario.id_comentario == AnaliseSentimento.id_comentario)
            .join(Video, Video.id_video == Comentario.id_video)
            .where(Video.id_execucao.in_(ids))
        )
        if ids
        else 0
    )

    # Vídeos DISTINTOS acompanhados, por youtube_video_id: o mesmo anúncio
    # coletado em duas execuções é um vídeo, não dois (VIDEOS é o retrato de
    # cada coleta e por isso repete a linha).
    videos_distintos = (
        await db.scalar(
            select(func.count(func.distinct(Video.youtube_video_id))).where(
                Video.id_execucao.in_(ids)
            )
        )
        if ids
        else 0
    )

    # --- destaque: a última concluída ---
    destaque = None
    if concluidas:
        ultima = concluidas[0]  # a lista já vem por id decrescente
        nome = next(
            (m.nome for m in modelos if m.id_modelo == ultima.id_modelo),
            "",
        )
        distribuicao = distribuicao_de(contagens.get(ultima.id_execucao, {}))
        destaque = DestaqueExecucao(
            id_execucao=ultima.id_execucao,
            nome_modelo_analise=nome,
            concluido_em=ultima.concluido_em,
            total_comentarios=distribuicao.total,
            total_videos=totais_video.get(ultima.id_execucao, 0),
            total_temas=totais_tema.get(ultima.id_execucao, 0),
            distribuicao=distribuicao,
        )

    # --- linhas de "Seus modelos" ---
    por_modelo: dict[int, list[Execucao]] = defaultdict(list)
    for execucao in execucoes:
        por_modelo[execucao.id_modelo].append(execucao)
    motivos = await _motivos_de_falha(
        db, [e.id_execucao for e in execucoes if e.status == STATUS_ERRO]
    )

    linhas_modelo: list[ModeloNoPainel] = []
    for modelo in modelos:
        do_modelo = por_modelo.get(modelo.id_modelo, [])
        ultima = do_modelo[0] if do_modelo else None
        concluida = next((e for e in do_modelo if e.status == STATUS_CONCLUIDA), None)
        filtros = modelo.filtros or {}
        linhas_modelo.append(
            ModeloNoPainel(
                id_modelo=modelo.id_modelo,
                nome=modelo.nome,
                total_videos=len(filtros.get("videos") or []),
                status_ultima_execucao=ultima.status if ultima else None,
                ultima_execucao_em=(
                    (ultima.concluido_em or ultima.iniciado_em) if ultima else None
                ),
                motivo_da_falha=(
                    motivos.get(ultima.id_execucao)
                    if ultima is not None and ultima.status == STATUS_ERRO
                    else None
                ),
                id_execucao_concluida=concluida.id_execucao if concluida else None,
            )
        )

    # --- versão do classificador em uso ---
    if concluidas:
        # A que classificou a execução mais recente: é a que o painel descreve.
        versao = await versao_modelo_da_execucao(db, concluidas[0].id_execucao)
    else:
        ativa = await db.scalar(
            select(VersaoModelo)
            .where(VersaoModelo.status == "ativo")
            .order_by(VersaoModelo.id_versao.desc())
        )
        versao = versao_para_resposta(ativa, None) if ativa is not None else None

    logger.info(
        "painel montado id_usuario=%s execucoes=%s concluidas=%s modelos=%s analisados=%s",
        usuario.id_usuario,
        len(execucoes),
        len(concluidas),
        len(modelos),
        analisados_total,
    )

    return ResumoPainel(
        destaque=destaque,
        modelos=linhas_modelo,
        totais=TotaisUsuario(
            comentarios_analisados=int(analisados_total or 0),
            execucoes_concluidas=len(concluidas),
            videos_acompanhados=int(videos_distintos or 0),
        ),
        # Nulo por ausência de registro, não por erro: ninguém contabiliza o
        # consumo de cota ainda. Ver `schemas/painel.py`.
        cota_youtube=None,
        versao_modelo=versao,
    )
