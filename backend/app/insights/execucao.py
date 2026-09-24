"""As regras que olham UMA execução.

Cada regra é uma função pura `agregados -> Fato | None` (ou `-> list[Fato]`), e
devolver `None` é o caminho normal, não a exceção: uma execução sem tema grande
o bastante simplesmente não tem "tema mais criticado". A alternativa — devolver
o melhor disponível e deixar a tela decidir se mostra — espalharia a regra de
decisão por duas camadas e acabaria mostrando o achado de 4 comentários em algum
lugar.

`fatos_da_execucao` é o que o futuro endpoint chama. A ordem da lista é a de
relevância para a tela: o que exige ação primeiro (crítica), o que é contexto
depois.
"""

from __future__ import annotations

from app.insights.agregados import AgregadosExecucao, TemaAgregado, VideoAgregado
from app.insights.configuracao import PADRAO, ConfiguracaoInsights
from app.insights.estatistica import pontos_percentuais
from app.insights.fatos import Amostra, Fato, Origem, TipoFato, Valor
from app.insights.frases import redigir


def _montar(
    tipo: TipoFato,
    valores: dict[str, Valor],
    amostra: Amostra,
    origem: Origem,
) -> Fato:
    """Constrói o fato e redige a frase dele no mesmo lugar.

    Existe para que nenhuma regra possa criar um `Fato` com `texto` vazio: a
    frase é parte do fato, e um fato sem frase chegaria à tela como card em
    branco.
    """
    return Fato(
        tipo=tipo,
        valores=valores,
        amostra=amostra,
        origem=origem,
        texto=redigir(tipo, valores),
    )


def _temas_com_amostra(
    agregados: AgregadosExecucao, config: ConfiguracaoInsights
) -> list[TemaAgregado]:
    return [tema for tema in agregados.temas if tema.distribuicao.total >= config.minimo_tema]


def tema_mais_criticado(
    agregados: AgregadosExecucao, config: ConfiguracaoInsights = PADRAO
) -> Fato | None:
    """O tema com a maior FRAÇÃO de negativos entre os que têm amostra.

    Fração e não contagem: o tema com mais comentários negativos costuma ser
    simplesmente o tema maior, e apontá-lo diria "o assunto mais falado também é
    o mais falado". O que interessa à PME é onde a proporção destoa.

    O desempate é pelo `id_tema`, para que duas execuções com os mesmos números
    produzam o mesmo fato — sem isso a saída dependeria da ordem em que a
    consulta devolveu as linhas.
    """
    candidatos = _temas_com_amostra(agregados, config)
    if not candidatos:
        return None

    tema = min(candidatos, key=lambda t: (-t.distribuicao.fracao_negativa, t.id_tema))
    return _montar(
        TipoFato.TEMA_MAIS_CRITICADO,
        {
            "rotulo_tema": tema.rotulo_tema,
            "percentual_negativo": pontos_percentuais(tema.distribuicao.fracao_negativa),
            "percentual_negativo_execucao": pontos_percentuais(
                agregados.distribuicao.fracao_negativa
            ),
            "comentarios_no_tema": tema.distribuicao.total,
            "comentarios_negativos_no_tema": tema.distribuicao.negativo,
        },
        Amostra(tamanho=tema.distribuicao.total, minimo_exigido=config.minimo_tema),
        Origem(id_execucoes=(agregados.id_execucao,), id_tema=tema.id_tema),
    )


def tema_melhor_recebido(
    agregados: AgregadosExecucao, config: ConfiguracaoInsights = PADRAO
) -> Fato | None:
    """O tema com a maior fração de positivos entre os que têm amostra."""
    candidatos = _temas_com_amostra(agregados, config)
    if not candidatos:
        return None

    tema = min(candidatos, key=lambda t: (-t.distribuicao.fracao_positiva, t.id_tema))
    return _montar(
        TipoFato.TEMA_MELHOR_RECEBIDO,
        {
            "rotulo_tema": tema.rotulo_tema,
            "percentual_positivo": pontos_percentuais(tema.distribuicao.fracao_positiva),
            "percentual_positivo_execucao": pontos_percentuais(
                agregados.distribuicao.fracao_positiva
            ),
            "comentarios_no_tema": tema.distribuicao.total,
            "comentarios_positivos_no_tema": tema.distribuicao.positivo,
        },
        Amostra(tamanho=tema.distribuicao.total, minimo_exigido=config.minimo_tema),
        Origem(id_execucoes=(agregados.id_execucao,), id_tema=tema.id_tema),
    )


def videos_muito_negativos(
    agregados: AgregadosExecucao, config: ConfiguracaoInsights = PADRAO
) -> list[Fato]:
    """Vídeos cuja fração negativa alcança `multiplo_video_negativo` vezes a da execução.

    Lista, e não um só: quando três vídeos de uma campanha destoam, os três
    interessam — é um padrão, e mostrar apenas o pior o esconderia.

    A comparação é contra a marca da EXECUÇÃO, e não contra a média das frações
    dos vídeos. A média de frações dá o mesmo peso a um vídeo de 20 comentários
    e a um de 2.000; a fração da execução é a proporção real do público, que é a
    referência que a PME tem em mente ao ler "o dobro da média".

    Execução sem nenhum negativo devolve lista vazia: com a marca em zero, todo
    vídeo com um único negativo seria "infinitas vezes a média".
    """
    marca = agregados.distribuicao.fracao_negativa
    if marca <= 0.0:
        return []

    limite = marca * config.multiplo_video_negativo
    achados: list[VideoAgregado] = [
        video
        for video in agregados.videos
        if video.distribuicao.total >= config.minimo_video
        and video.distribuicao.fracao_negativa >= limite
    ]
    achados.sort(key=lambda v: (-v.distribuicao.fracao_negativa, v.id_video))

    return [
        _montar(
            TipoFato.VIDEO_MUITO_NEGATIVO,
            {
                "titulo": video.titulo,
                "youtube_video_id": video.youtube_video_id,
                "percentual_negativo": pontos_percentuais(video.distribuicao.fracao_negativa),
                "percentual_negativo_execucao": pontos_percentuais(marca),
                "multiplo_da_media": round(video.distribuicao.fracao_negativa / marca, 1),
                "comentarios_no_video": video.distribuicao.total,
                "comentarios_negativos_no_video": video.distribuicao.negativo,
            },
            Amostra(tamanho=video.distribuicao.total, minimo_exigido=config.minimo_video),
            Origem(
                id_execucoes=(agregados.id_execucao,),
                id_video=video.id_video,
                youtube_video_id=video.youtube_video_id,
            ),
        )
        for video in achados
    ]


def concentracao_das_criticas(
    agregados: AgregadosExecucao, config: ConfiguracaoInsights = PADRAO
) -> Fato | None:
    """Poucos temas respondem pela maior parte dos comentários negativos?

    A conta: ordena os temas por contagem de negativos, vai somando do maior
    para o menor e para quando alcança `fracao_concentracao` das críticas. Se o
    número de temas que bastou for no máximo `maxima_fracao_de_temas` do total,
    é concentração.

    **Os dois cortes são necessários.** Só o primeiro diria que 8 de 10 temas
    concentram 60% das críticas — que é dispersão descrita como concentração. Só
    o segundo não diria nada sobre quanto da crítica os temas apontados somam.

    O denominador é a soma de negativos POR TEMA, e não o total de negativos da
    execução. São números diferentes: COMENTARIO_TEMA é N:N, um comentário pode
    contar em dois temas e um comentário sem tema não conta em nenhum. A frase
    fala de "comentários negativos da execução" no sentido de "dos que estão
    ligados a algum tema", e é essa a base contra a qual a porcentagem fecha.
    """
    com_negativo = [tema for tema in agregados.temas if tema.distribuicao.negativo > 0]
    if not com_negativo:
        return None

    total_negativo = sum(tema.distribuicao.negativo for tema in com_negativo)
    ordenados = sorted(com_negativo, key=lambda t: (-t.distribuicao.negativo, t.id_tema))

    alvo = total_negativo * config.fracao_concentracao
    acumulado = 0
    apontados: list[TemaAgregado] = []
    for tema in ordenados:
        apontados.append(tema)
        acumulado += tema.distribuicao.negativo
        if acumulado >= alvo:
            break

    if len(apontados) > len(agregados.temas) * config.maxima_fracao_de_temas:
        return None

    amostra = sum(tema.distribuicao.total for tema in apontados)
    return _montar(
        TipoFato.CONCENTRACAO_DAS_CRITICAS,
        {
            "temas_apontados": len(apontados),
            "temas_na_execucao": len(agregados.temas),
            "percentual_das_criticas": pontos_percentuais(acumulado / total_negativo),
            "comentarios_negativos_apontados": acumulado,
            "comentarios_negativos_com_tema": total_negativo,
            "rotulos": ", ".join(tema.rotulo_tema for tema in apontados),
        },
        Amostra(tamanho=amostra, minimo_exigido=config.minimo_tema),
        # Um fato sobre um CONJUNTO de temas não tem um `id_tema` só. A tela usa
        # `rotulos` no texto e volta à lista de temas pelo link da execução;
        # preencher aqui o id do primeiro apontado faria o card linkar para um
        # tema que é só parte do que ele afirma.
        Origem(id_execucoes=(agregados.id_execucao,)),
    )


def fatos_da_execucao(
    agregados: AgregadosExecucao, config: ConfiguracaoInsights = PADRAO
) -> list[Fato]:
    """Todos os fatos de uma execução, em ordem de relevância para a tela.

    Execução abaixo de `minimo_execucao` não produz fato NENHUM, mesmo que um
    tema isolado passasse no corte de tema: a afirmação "o tema mais criticado
    desta execução" pressupõe que exista execução com o que comparar.
    """
    if agregados.distribuicao.total < config.minimo_execucao:
        return []

    fatos: list[Fato] = []
    if (criticado := tema_mais_criticado(agregados, config)) is not None:
        fatos.append(criticado)
    if (concentracao := concentracao_das_criticas(agregados, config)) is not None:
        fatos.append(concentracao)
    fatos.extend(videos_muito_negativos(agregados, config))
    if (recebido := tema_melhor_recebido(agregados, config)) is not None:
        fatos.append(recebido)
    return fatos
