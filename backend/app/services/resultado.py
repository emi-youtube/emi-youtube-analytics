"""Leitura dos resultados de uma execução (telas Resultados e Comentários).

**Tudo que é contagem acontece no banco.** São até 5.000 comentários por
execução (CLAUDE.md Seção 1): trazer as linhas para somar em laço no Python
custaria a transferência inteira para produzir três inteiros, e o `GROUP BY` já
faz isso ao lado do dado. Os laços que sobraram aqui percorrem o RESULTADO de um
`GROUP BY` — no máximo três linhas por vídeo ou por tema —, nunca comentários.

**Nada aqui decide se o usuário pode ver.** Toda rota passa primeiro por
`services.execucao.get_owned`, que faz join com MODELOS_ANALISE pelo usuário do
token e responde 404 quando a execução é de outro — nunca 403, que confirmaria
que aquele id existe.

**As consultas de tema já estão escritas.** TEMAS e COMENTARIO_TEMA não têm
linha nenhuma porque o worker de tópicos não existe, então hoje elas devolvem
listas vazias. Estão aqui, e testadas com dados sintéticos, para acenderem
sozinhas quando o worker chegar — em vez de virarem um segundo card de trabalho.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights import (
    AgregadosExecucao,
    Distribuicao,
    TemaAgregado,
    VideoAgregado,
    fatos_da_campanha,
    fatos_da_execucao,
)
from app.insights.fatos import Fato
from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.comentario_tema import ComentarioTema
from app.models.execucao import Execucao
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video
from app.schemas.resultado import (
    AlcanceExecucao,
    AmostraInsight,
    ComentarioAnalisado,
    DistribuicaoSentimento,
    FatoInsight,
    MetricasAvaliacao,
    OrigemInsight,
    PaginaComentarios,
    PontoDeAtencao,
    ResultadoDisponivel,
    ResultadoExecucao,
    TemaComSentimento,
    TemaDoComentario,
    TemaResponse,
    VersaoModeloResponse,
    VideoComSentimento,
    VideoResponse,
    VideoResumido,
)
from app.services.execucao import get_owned

logger = logging.getLogger(__name__)

STATUS_CONCLUIDA = "concluida"
SENTIMENTOS = ("positivo", "neutro", "negativo")

# Caracteres que o LIKE trata como curinga. Sem escapar, uma busca por "100%"
# casaria com todo comentário da execução.
CURINGAS_LIKE = ("\\", "%", "_")


# --------------------------------------------------------------------------- helpers


def distribuicao_de(contagens: dict[str, int]) -> DistribuicaoSentimento:
    positivo = contagens.get("positivo", 0)
    neutro = contagens.get("neutro", 0)
    negativo = contagens.get("negativo", 0)
    return DistribuicaoSentimento(
        positivo=positivo,
        neutro=neutro,
        negativo=negativo,
        total=positivo + neutro + negativo,
    )


def _para_motor(contagens: dict[str, int]) -> Distribuicao:
    """A mesma contagem no formato do motor de insights (que calcula frações)."""
    return Distribuicao(
        positivo=contagens.get("positivo", 0),
        neutro=contagens.get("neutro", 0),
        negativo=contagens.get("negativo", 0),
    )


def _escapar_like(termo: str) -> str:
    for curinga in CURINGAS_LIKE:
        termo = termo.replace(curinga, f"\\{curinga}")
    return termo


def _comentarios_da_execucao(id_execucao: int) -> Select:
    """Subconsulta base: os comentários daquela execução, via VIDEOS.

    COMENTARIOS não tem `id_execucao` — ele pendura em VIDEOS, que é o retrato
    da coleta. Este join é, por isso, o recorte de execução de tudo neste módulo.
    """
    return (
        select(Comentario.id_comentario)
        .join(Video, Video.id_video == Comentario.id_video)
        .where(Video.id_execucao == id_execucao)
    )


# --------------------------------------------------------------------------- agregações


async def contagens_por_execucao(db: AsyncSession, ids: Sequence[int]) -> dict[int, dict[str, int]]:
    """`{id_execucao: {sentimento: contagem}}` num único GROUP BY."""
    if not ids:
        return {}
    linhas = await db.execute(
        select(Video.id_execucao, AnaliseSentimento.sentimento, func.count())
        .join(Comentario, Comentario.id_video == Video.id_video)
        .join(AnaliseSentimento, AnaliseSentimento.id_comentario == Comentario.id_comentario)
        .where(Video.id_execucao.in_(ids))
        .group_by(Video.id_execucao, AnaliseSentimento.sentimento)
    )
    resultado: dict[int, dict[str, int]] = defaultdict(dict)
    for id_execucao, sentimento, quantidade in linhas:
        resultado[id_execucao][sentimento] = quantidade
    return resultado


async def _contagens_por_video(db: AsyncSession, ids: Sequence[int]) -> dict[int, dict[str, int]]:
    """`{id_video: {sentimento: contagem}}`."""
    if not ids:
        return {}
    linhas = await db.execute(
        select(Comentario.id_video, AnaliseSentimento.sentimento, func.count())
        .join(AnaliseSentimento, AnaliseSentimento.id_comentario == Comentario.id_comentario)
        .join(Video, Video.id_video == Comentario.id_video)
        .where(Video.id_execucao.in_(ids))
        .group_by(Comentario.id_video, AnaliseSentimento.sentimento)
    )
    resultado: dict[int, dict[str, int]] = defaultdict(dict)
    for id_video, sentimento, quantidade in linhas:
        resultado[id_video][sentimento] = quantidade
    return resultado


async def _contagens_por_tema(db: AsyncSession, ids: Sequence[int]) -> dict[int, dict[str, int]]:
    """`{id_tema: {sentimento: contagem}}` — vazio até o worker de tópicos existir."""
    if not ids:
        return {}
    linhas = await db.execute(
        select(ComentarioTema.id_tema, AnaliseSentimento.sentimento, func.count())
        .join(Tema, Tema.id_tema == ComentarioTema.id_tema)
        .join(
            AnaliseSentimento,
            AnaliseSentimento.id_comentario == ComentarioTema.id_comentario,
        )
        .where(Tema.id_execucao.in_(ids))
        .group_by(ComentarioTema.id_tema, AnaliseSentimento.sentimento)
    )
    resultado: dict[int, dict[str, int]] = defaultdict(dict)
    for id_tema, sentimento, quantidade in linhas:
        resultado[id_tema][sentimento] = quantidade
    return resultado


async def _videos(db: AsyncSession, ids: Sequence[int]) -> dict[int, list[Video]]:
    if not ids:
        return {}
    linhas = await db.scalars(
        select(Video).where(Video.id_execucao.in_(ids)).order_by(Video.id_video)
    )
    por_execucao: dict[int, list[Video]] = defaultdict(list)
    for video in linhas.all():
        por_execucao[video.id_execucao].append(video)
    return por_execucao


async def _temas(db: AsyncSession, ids: Sequence[int]) -> dict[int, list[Tema]]:
    if not ids:
        return {}
    linhas = await db.scalars(select(Tema).where(Tema.id_execucao.in_(ids)).order_by(Tema.id_tema))
    por_execucao: dict[int, list[Tema]] = defaultdict(list)
    for tema in linhas.all():
        por_execucao[tema.id_execucao].append(tema)
    return por_execucao


async def _alcance(db: AsyncSession, id_execucao: int) -> AlcanceExecucao:
    """Somas de VIDEOS + total de comentários COLETADOS (não analisados).

    Alcance é sobre o quanto o anúncio circulou; `distribuicao.total` é sobre o
    quanto foi classificado. Os dois podem divergir num reprocessamento pela
    metade, e é honesto que divirjam — misturá-los esconderia isso.
    """
    somas = (
        await db.execute(
            select(
                func.coalesce(func.sum(Video.visualizacoes), 0),
                func.coalesce(func.sum(Video.curtidas), 0),
            ).where(Video.id_execucao == id_execucao)
        )
    ).one()
    total_comentarios = await db.scalar(
        select(func.count())
        .select_from(Comentario)
        .join(Video, Video.id_video == Comentario.id_video)
        .where(Video.id_execucao == id_execucao)
    )

    visualizacoes = int(somas[0] or 0)
    curtidas = int(somas[1] or 0)
    comentarios = int(total_comentarios or 0)
    # Sem view não existe taxa por mil views: zero, não divisão por zero.
    por_mil = round(comentarios / (visualizacoes / 1000), 2) if visualizacoes else 0.0
    return AlcanceExecucao(
        visualizacoes=visualizacoes,
        curtidas=curtidas,
        comentarios=comentarios,
        comentarios_por_mil_views=por_mil,
    )


async def agregados(db: AsyncSession, ids: Sequence[int]) -> dict[int, AgregadosExecucao]:
    """Monta o `AgregadosExecucao` do motor de insights para várias execuções.

    Recebe uma LISTA de ids e resolve tudo em consultas agrupadas porque os
    insights de campanha precisam dos agregados de todas as coletas do mesmo
    modelo. Uma versão por execução viraria N+1 com N = número de coletas.
    """
    if not ids:
        return {}

    execucoes = (await db.scalars(select(Execucao).where(Execucao.id_execucao.in_(ids)))).all()
    por_execucao = await contagens_por_execucao(db, ids)
    videos = await _videos(db, ids)
    temas = await _temas(db, ids)
    por_video = await _contagens_por_video(db, ids)
    por_tema = await _contagens_por_tema(db, ids)

    montados: dict[int, AgregadosExecucao] = {}
    for execucao in execucoes:
        montados[execucao.id_execucao] = AgregadosExecucao(
            id_execucao=execucao.id_execucao,
            id_modelo=execucao.id_modelo,
            distribuicao=_para_motor(por_execucao.get(execucao.id_execucao, {})),
            temas=tuple(
                TemaAgregado(
                    id_tema=tema.id_tema,
                    rotulo_tema=tema.rotulo_tema,
                    distribuicao=_para_motor(por_tema.get(tema.id_tema, {})),
                    palavras_chave=tuple(tema.palavras_chave or ()),
                )
                for tema in temas.get(execucao.id_execucao, [])
            ),
            videos=tuple(
                VideoAgregado(
                    id_video=video.id_video,
                    youtube_video_id=video.youtube_video_id,
                    titulo=video.titulo,
                    distribuicao=_para_motor(por_video.get(video.id_video, {})),
                )
                for video in videos.get(execucao.id_execucao, [])
            ),
            concluido_em=execucao.concluido_em,
        )
    return montados


# --------------------------------------------------------------------------- versão do modelo


async def versao_modelo_da_execucao(
    db: AsyncSession, id_execucao: int
) -> VersaoModeloResponse | None:
    """A versão que classificou esta execução, com `em_uso_desde`.

    Sai das PRÓPRIAS análises da execução, e não da versão `ativo`: o histórico
    tem que continuar dizendo a verdade depois de o BERTimbau substituir o
    léxico. Se a execução não classificou nada (todos os vídeos com comentário
    desabilitado), cai na versão `ativo` — é a que a teria classificado — e só
    devolve nulo quando nem isso existe.
    """
    linha = (
        await db.execute(
            select(
                AnaliseSentimento.id_versao_modelo,
                func.min(AnaliseSentimento.processado_em),
                func.count(),
            )
            .join(Comentario, Comentario.id_comentario == AnaliseSentimento.id_comentario)
            .join(Video, Video.id_video == Comentario.id_video)
            .where(Video.id_execucao == id_execucao)
            .group_by(AnaliseSentimento.id_versao_modelo)
            .order_by(func.count().desc(), AnaliseSentimento.id_versao_modelo)
            .limit(1)
        )
    ).first()

    if linha is None:
        versao = await db.scalar(
            select(VersaoModelo)
            .where(VersaoModelo.status == "ativo")
            .order_by(VersaoModelo.id_versao.desc())
        )
        return versao_para_resposta(versao, None) if versao is not None else None

    id_versao, em_uso_desde, _ = linha
    versao = await db.get(VersaoModelo, id_versao)
    return versao_para_resposta(versao, em_uso_desde) if versao is not None else None


def versao_para_resposta(
    versao: VersaoModelo, em_uso_desde: datetime | None
) -> VersaoModeloResponse:
    return VersaoModeloResponse(
        id_versao=versao.id_versao,
        nome_modelo=versao.nome_modelo,
        versao=versao.versao,
        metricas_avaliacao=_metricas(versao.metricas_avaliacao),
        status=versao.status,
        em_uso_desde=em_uso_desde,
    )


def _metricas(bruto: dict | None) -> MetricasAvaliacao | None:
    """Só devolve métrica quando existe AVALIAÇÃO — e `f1_macro` é o que a marca.

    O classificador léxico grava `{"proveniencia": {...}}`: sha256 do recurso,
    contagem de entradas, papel. Isso não é avaliação — ele nunca foi medido
    contra o gabarito humano, que é o único válido (CLAUDE.md regra 6). Sem
    `f1_macro`, a resposta é nula e a tela mostra "sem métrica registrada".
    """
    if not bruto or "f1_macro" not in bruto:
        return None
    try:
        return MetricasAvaliacao.model_validate(bruto)
    except ValueError:
        logger.warning("metricas_avaliacao presente mas ilegivel; tratando como ausente")
        return None


# --------------------------------------------------------------------------- comentários


def _consulta_comentario_analisado(id_execucao: int) -> Select:
    """Comentário + análise + vídeo resumido, o trio que a tela sempre mostra junto."""
    return (
        select(Comentario, AnaliseSentimento, Video)
        .join(Video, Video.id_video == Comentario.id_video)
        .join(AnaliseSentimento, AnaliseSentimento.id_comentario == Comentario.id_comentario)
        .where(Video.id_execucao == id_execucao)
    )


async def _temas_dos_comentarios(
    db: AsyncSession, ids: Sequence[int]
) -> dict[int, list[TemaDoComentario]]:
    """`{id_comentario: [temas]}`, do maior peso para o menor. Vazio sem tópicos."""
    if not ids:
        return {}
    linhas = await db.execute(
        select(ComentarioTema.id_comentario, Tema.id_tema, Tema.rotulo_tema, ComentarioTema.peso)
        .join(Tema, Tema.id_tema == ComentarioTema.id_tema)
        .where(ComentarioTema.id_comentario.in_(ids))
        .order_by(ComentarioTema.id_comentario, ComentarioTema.peso.desc(), Tema.id_tema)
    )
    agrupado: dict[int, list[TemaDoComentario]] = defaultdict(list)
    for id_comentario, id_tema, rotulo, peso in linhas:
        agrupado[id_comentario].append(
            TemaDoComentario(id_tema=id_tema, rotulo_tema=rotulo, peso=float(peso))
        )
    return agrupado


async def _montar_analisados(
    db: AsyncSession, linhas: Iterable[tuple[Comentario, AnaliseSentimento, Video]]
) -> list[ComentarioAnalisado]:
    materializadas = list(linhas)
    temas = await _temas_dos_comentarios(
        db, [comentario.id_comentario for comentario, _, _ in materializadas]
    )
    return [
        ComentarioAnalisado(
            comentario=comentario,
            analise=analise,
            video=VideoResumido.model_validate(video),
            temas=temas.get(comentario.id_comentario, []),
        )
        for comentario, analise, video in materializadas
    ]


async def comentarios_representativos(
    db: AsyncSession, id_execucao: int
) -> list[ComentarioAnalisado]:
    """Um comentário por sentimento, escolhido por CRITÉRIO FIXO — nada aleatório.

    **O critério: o comentário de comprimento MEDIANO daquele sentimento**,
    desempatado pelo menor `id_comentario`.

    Por que a mediana, e não o mais longo ou o mais curto: o mais longo é quase
    sempre um desabafo atípico, e o mais curto é "kkkk" ou um emoji. O mediano é
    o espécime mais típico da classe — é o que o usuário precisa ler para
    entender o que o rótulo quer dizer naquela execução.

    Por que não aleatório: a tela seria diferente a cada recarga sobre o mesmo
    dado, e a banca não poderia reproduzir a figura do relatório. Sendo
    determinístico, o mesmo resultado sai sempre da mesma execução.

    **Isto é interino, e está marcado como tal.** O CLAUDE.md Seção 11 define o
    critério definitivo — o comentário mais central de cada TEMA na
    representação do próprio BERTimbau. Ele depende do worker de tópicos e de
    embeddings, que não existem; até então, a mediana por sentimento é o
    critério mais defensável que não exige nenhum dos dois.
    """
    posicao = (
        func.row_number()
        .over(
            partition_by=AnaliseSentimento.sentimento,
            order_by=(func.length(Comentario.texto), Comentario.id_comentario),
        )
        .label("posicao")
    )
    total = func.count().over(partition_by=AnaliseSentimento.sentimento).label("total")

    ranqueados = (
        select(Comentario.id_comentario.label("id_comentario"), posicao, total)
        .join(Video, Video.id_video == Comentario.id_video)
        .join(AnaliseSentimento, AnaliseSentimento.id_comentario == Comentario.id_comentario)
        .where(Video.id_execucao == id_execucao)
        .subquery()
    )

    # Divisão inteira: total 1 -> 1, total 2 -> 1 (mediana baixa), 3 -> 2, 4 -> 2.
    escolhidos = await db.scalars(
        select(ranqueados.c.id_comentario).where(
            ranqueados.c.posicao == (ranqueados.c.total + 1) / 2
        )
    )
    ids = list(escolhidos.all())
    if not ids:
        return []

    linhas = await db.execute(
        _consulta_comentario_analisado(id_execucao)
        .where(Comentario.id_comentario.in_(ids))
        # Ordem estável e legível na tela: positivo, neutro, negativo.
        .order_by(AnaliseSentimento.sentimento, Comentario.id_comentario)
    )
    analisados = await _montar_analisados(db, linhas.all())
    ordem = {sentimento: indice for indice, sentimento in enumerate(SENTIMENTOS)}
    return sorted(analisados, key=lambda item: ordem.get(item.analise.sentimento, 99))


async def pagina_de_comentarios(
    db: AsyncSession,
    id_execucao: int,
    *,
    pagina: int,
    tamanho: int,
    busca: str | None = None,
    id_tema: int | None = None,
    id_video: int | None = None,
    sentimento: str | None = None,
) -> PaginaComentarios:
    """Página de comentários da execução, com os filtros da tela aplicados no SQL.

    `contagem_por_sentimento` ignora de propósito o filtro de sentimento: os
    chips "Positivo · 160 / Neutro · 198" têm de continuar mostrando os três
    números depois que o usuário clica num deles, senão o único chip que sobra é
    o que ele já escolheu.
    """
    # Os filtros viram uma LISTA de condições, e não uma consulta que vai sendo
    # embrulhada: as três consultas abaixo (contagem por sentimento, total,
    # página) precisam das mesmas condições com junções diferentes, e compor a
    # partir de subconsultas faria as colunas deixarem de resolver.
    condicoes = [Video.id_execucao == id_execucao]
    if busca and busca.strip():
        condicoes.append(Comentario.texto.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    if id_video is not None:
        condicoes.append(Comentario.id_video == id_video)
    if id_tema is not None:
        condicoes.append(
            select(ComentarioTema.id_comentario)
            .where(
                ComentarioTema.id_comentario == Comentario.id_comentario,
                ComentarioTema.id_tema == id_tema,
            )
            .exists()
        )

    # Contagem por sentimento SEM o filtro de sentimento — ver docstring.
    contagens = await db.execute(
        select(AnaliseSentimento.sentimento, func.count())
        .select_from(Comentario)
        .join(Video, Video.id_video == Comentario.id_video)
        .join(AnaliseSentimento, AnaliseSentimento.id_comentario == Comentario.id_comentario)
        .where(*condicoes)
        .group_by(AnaliseSentimento.sentimento)
    )
    por_sentimento = {sentimento_: quantidade for sentimento_, quantidade in contagens}

    if sentimento is not None:
        condicoes.append(AnaliseSentimento.sentimento == sentimento)

    total = await db.scalar(
        select(func.count())
        .select_from(Comentario)
        .join(Video, Video.id_video == Comentario.id_video)
        .join(AnaliseSentimento, AnaliseSentimento.id_comentario == Comentario.id_comentario)
        .where(*condicoes)
    )

    pagina = max(1, pagina)
    linhas = await db.execute(
        _consulta_comentario_analisado(id_execucao)
        .where(*condicoes)
        .order_by(Comentario.id_comentario)
        .offset((pagina - 1) * tamanho)
        .limit(tamanho)
    )

    return PaginaComentarios(
        itens=await _montar_analisados(db, linhas.all()),
        total=int(total or 0),
        pagina=pagina,
        tamanho=tamanho,
        contagem_por_sentimento=distribuicao_de(por_sentimento),
    )


# --------------------------------------------------------------------------- insights


def _fato_para_resposta(fato: Fato) -> FatoInsight:
    return FatoInsight(
        tipo=fato.tipo.value,
        valores=dict(fato.valores),
        amostra=AmostraInsight(
            tamanho=fato.amostra.tamanho, minimo_exigido=fato.amostra.minimo_exigido
        ),
        origem=OrigemInsight(
            id_execucoes=list(fato.origem.id_execucoes),
            id_tema=fato.origem.id_tema,
            id_video=fato.origem.id_video,
            youtube_video_id=fato.origem.youtube_video_id,
        ),
        texto=fato.texto,
    )


def _ponto_de_atencao(fatos: Sequence[FatoInsight]) -> PontoDeAtencao | None:
    """Preenche o campo DEPRECIADO a partir do fato de tema mais criticado.

    Continua no contrato só enquanto `resultado.html` não migra para `insights`.
    Derivado, e não calculado de novo: duas regras para a mesma afirmação
    poderiam discordar na tela.
    """
    for fato in fatos:
        if fato.tipo == "tema_mais_criticado" and fato.origem.id_tema is not None:
            return PontoDeAtencao(
                id_tema=fato.origem.id_tema,
                rotulo_tema=str(fato.valores.get("rotulo_tema", "")),
                texto=fato.texto,
            )
    return None


# --------------------------------------------------------------------------- resposta


async def resultado_da_execucao(
    db: AsyncSession, usuario: Usuario, id_execucao: int
) -> ResultadoExecucao:
    """Monta a tela Resultados inteira. 404 se a execução não é do usuário."""
    execucao = await get_owned(db, usuario, id_execucao)
    modelo = await db.get(ModeloAnalise, execucao.id_modelo)

    todos = await agregados(db, [id_execucao])
    desta = todos[id_execucao]

    # Campanha: as coletas CONCLUÍDAS do mesmo modelo, esta inclusive. O motor
    # ordena cronologicamente e só afirma o que passa da margem de incerteza.
    ids_da_campanha = list(
        (
            await db.scalars(
                select(Execucao.id_execucao).where(
                    Execucao.id_modelo == execucao.id_modelo,
                    Execucao.status == STATUS_CONCLUIDA,
                )
            )
        ).all()
    )
    if id_execucao not in ids_da_campanha:
        ids_da_campanha.append(id_execucao)
    da_campanha = await agregados(db, ids_da_campanha)

    insights = [_fato_para_resposta(fato) for fato in fatos_da_execucao(desta)]
    insights_campanha = [
        _fato_para_resposta(fato)
        for fato in fatos_da_campanha(tuple(da_campanha[i] for i in sorted(da_campanha)))
    ]

    videos = await _videos(db, [id_execucao])
    temas = await _temas(db, [id_execucao])
    por_video = await _contagens_por_video(db, [id_execucao])
    por_tema = await _contagens_por_tema(db, [id_execucao])

    logger.info(
        "resultado montado id_execucao=%s comentarios_analisados=%s videos=%s temas=%s "
        "insights=%s insights_campanha=%s",
        id_execucao,
        desta.distribuicao.total,
        len(videos.get(id_execucao, [])),
        len(temas.get(id_execucao, [])),
        len(insights),
        len(insights_campanha),
    )

    return ResultadoExecucao(
        id_execucao=id_execucao,
        id_modelo=execucao.id_modelo,
        nome_modelo_analise=modelo.nome if modelo is not None else "",
        concluido_em=execucao.concluido_em,
        distribuicao=distribuicao_de(
            {
                "positivo": desta.distribuicao.positivo,
                "neutro": desta.distribuicao.neutro,
                "negativo": desta.distribuicao.negativo,
            }
        ),
        alcance=await _alcance(db, id_execucao),
        videos=[
            VideoComSentimento(
                video=VideoResponse.model_validate(video),
                distribuicao=distribuicao_de(por_video.get(video.id_video, {})),
            )
            for video in videos.get(id_execucao, [])
        ],
        temas=[
            TemaComSentimento(
                tema=TemaResponse.model_validate(tema),
                distribuicao=distribuicao_de(por_tema.get(tema.id_tema, {})),
            )
            for tema in temas.get(id_execucao, [])
        ],
        comentarios_representativos=await comentarios_representativos(db, id_execucao),
        insights=insights,
        insights_da_campanha=insights_campanha,
        ponto_de_atencao=_ponto_de_atencao(insights),
        versao_modelo=await versao_modelo_da_execucao(db, id_execucao),
    )


async def resultados_disponiveis(db: AsyncSession, usuario: Usuario) -> list[ResultadoDisponivel]:
    """As execuções concluídas do usuário, com o suficiente para escolher uma."""
    execucoes = (
        await db.execute(
            select(Execucao, ModeloAnalise.nome)
            .join(ModeloAnalise, ModeloAnalise.id_modelo == Execucao.id_modelo)
            .where(
                ModeloAnalise.id_usuario == usuario.id_usuario,
                Execucao.status == STATUS_CONCLUIDA,
            )
            .order_by(Execucao.id_execucao.desc())
        )
    ).all()
    if not execucoes:
        return []

    ids = [execucao.id_execucao for execucao, _ in execucoes]
    contagens = await contagens_por_execucao(db, ids)

    totais_video = {
        id_execucao: quantidade
        for id_execucao, quantidade in await db.execute(
            select(Video.id_execucao, func.count())
            .where(Video.id_execucao.in_(ids))
            .group_by(Video.id_execucao)
        )
    }
    totais_tema = {
        id_execucao: quantidade
        for id_execucao, quantidade in await db.execute(
            select(Tema.id_execucao, func.count())
            .where(Tema.id_execucao.in_(ids))
            .group_by(Tema.id_execucao)
        )
    }

    return [
        ResultadoDisponivel(
            id_execucao=execucao.id_execucao,
            id_modelo=execucao.id_modelo,
            nome_modelo_analise=nome,
            concluido_em=execucao.concluido_em,
            distribuicao=distribuicao_de(contagens.get(execucao.id_execucao, {})),
            total_videos=totais_video.get(execucao.id_execucao, 0),
            total_temas=totais_tema.get(execucao.id_execucao, 0),
        )
        for execucao, nome in execucoes
    ]


async def pagina_da_execucao(
    db: AsyncSession, usuario: Usuario, id_execucao: int, **filtros
) -> PaginaComentarios:
    """`pagina_de_comentarios` com o portão de dono na frente."""
    await get_owned(db, usuario, id_execucao)
    return await pagina_de_comentarios(db, id_execucao, **filtros)
