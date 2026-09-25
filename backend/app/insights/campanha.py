"""As regras que olham VÁRIAS execuções do mesmo modelo de análise.

Uma campanha, aqui, é a sequência de coletas de um mesmo `MODELOS_ANALISE`
(CLAUDE.md Seção 4: `EXECUCOES.id_modelo`). É o que permite dizer "piorou desde
a última coleta" em vez de só descrever o presente.

**Duas defesas contra a afirmação fácil**, e as duas são obrigatórias:

1. **amostra mínima nas DUAS coletas** (`minimo_variacao`). Comparar 2.000
   comentários com 40 não é comparar campanhas, é medir a segunda mal;
2. **margem de incerteza** (`estatistica.py`). Toda diferença que não excede a
   margem é descartada em silêncio — e é o caso comum, não a exceção.

**A comparação é entre coletas CONSECUTIVAS**, ordenadas no tempo, e não de
todas contra todas. Comparar todos os pares de cinco execuções daria dez fatos
sobre a mesma campanha, a maioria redundante, e multiplicaria a chance de um
falso positivo escapar da margem. A pergunta que a PME faz é "mudou desde a
última vez?".
"""

from __future__ import annotations

from itertools import pairwise

from app.insights.agregados import AgregadosExecucao, VideoAgregado
from app.insights.configuracao import PADRAO, ConfiguracaoInsights
from app.insights.estatistica import Comparacao, comparar_proporcoes, pontos_percentuais
from app.insights.fatos import Amostra, Fato, Origem, TipoFato, Valor
from app.insights.frases import redigir


def _montar(
    tipo: TipoFato,
    valores: dict[str, Valor],
    amostra: Amostra,
    origem: Origem,
) -> Fato:
    return Fato(
        tipo=tipo,
        valores=valores,
        amostra=amostra,
        origem=origem,
        texto=redigir(tipo, valores),
    )


def ordenar_execucoes(execucoes: tuple[AgregadosExecucao, ...]) -> list[AgregadosExecucao]:
    """Da coleta mais antiga para a mais nova.

    `concluido_em` é o critério, com `id_execucao` para desempatar e para cobrir
    execução ainda sem data de conclusão — que ordena pelo id, já que ids são
    crescentes por inserção. Sem um critério total, "antes" e "depois" ficariam a
    cargo da ordem em que a consulta devolveu as linhas, e o sinal da diferença
    (subiu/caiu) se inverteria sem aviso.
    """
    return sorted(
        execucoes,
        key=lambda execucao: (
            execucao.concluido_em is None,
            execucao.concluido_em.timestamp() if execucao.concluido_em else 0.0,
            execucao.id_execucao,
        ),
    )


def _comparar(
    antes: AgregadosExecucao, depois: AgregadosExecucao, config: ConfiguracaoInsights
) -> Comparacao:
    return comparar_proporcoes(
        positivos_antes=antes.distribuicao.negativo,
        tamanho_antes=antes.distribuicao.total,
        positivos_depois=depois.distribuicao.negativo,
        tamanho_depois=depois.distribuicao.total,
        z=config.z_confianca,
    )


def variacao_de_sentimento(
    execucoes: tuple[AgregadosExecucao, ...], config: ConfiguracaoInsights = PADRAO
) -> list[Fato]:
    """Variação da fração de negativos entre coletas consecutivas.

    Só sai fato quando a diferença excede a margem de incerteza. Um modelo com
    uma execução só devolve lista vazia — não há par a comparar, e isso é
    resultado normal, não erro.

    Mede o NEGATIVO, e não o positivo, por ser a métrica acionável: a PME age
    sobre rejeição que cresce. O positivo é o complemento de negativo e neutro e
    pode cair sem que a rejeição mude (migrando para neutro), o que daria um
    alarme sobre nada.
    """
    ordenadas = ordenar_execucoes(execucoes)
    fatos: list[Fato] = []

    for antes, depois in pairwise(ordenadas):
        if (
            antes.distribuicao.total < config.minimo_variacao
            or depois.distribuicao.total < config.minimo_variacao
        ):
            continue

        comparacao = _comparar(antes, depois, config)
        if not comparacao.significativa:
            continue

        fatos.append(
            _montar(
                TipoFato.VARIACAO_DE_SENTIMENTO,
                {
                    "percentual_negativo_antes": pontos_percentuais(comparacao.proporcao_antes),
                    "percentual_negativo_depois": pontos_percentuais(comparacao.proporcao_depois),
                    "diferenca_em_pontos": pontos_percentuais(comparacao.diferenca),
                    "margem_em_pontos": pontos_percentuais(comparacao.margem),
                    "comentarios_antes": comparacao.tamanho_antes,
                    "comentarios_depois": comparacao.tamanho_depois,
                    "id_execucao_antes": antes.id_execucao,
                    "id_execucao_depois": depois.id_execucao,
                },
                # A amostra do fato é a MENOR das duas: é ela que limita o que a
                # comparação consegue afirmar. Somar as duas inflaria o número
                # que a tela mostra como lastro da afirmação.
                Amostra(
                    tamanho=min(comparacao.tamanho_antes, comparacao.tamanho_depois),
                    minimo_exigido=config.minimo_variacao,
                ),
                Origem(id_execucoes=(antes.id_execucao, depois.id_execucao)),
            )
        )
    return fatos


def _videos_por_youtube_id(execucao: AgregadosExecucao) -> dict[str, VideoAgregado]:
    """Índice do vídeo pela chave que sobrevive entre coletas.

    `id_video` é local à execução (VIDEOS tem `id_execucao`), então casar por ele
    não casaria nada. O `youtube_video_id` é o mesmo vídeo no YouTube, que é o
    que a PME quer acompanhar.
    """
    return {video.youtube_video_id: video for video in execucao.videos}


def evolucao_dos_videos(
    execucoes: tuple[AgregadosExecucao, ...], config: ConfiguracaoInsights = PADRAO
) -> list[Fato]:
    """O mesmo vídeo, comparado entre coletas consecutivas.

    Mesmas duas defesas da variação de campanha, com o corte próprio de vídeo
    (`minimo_video_entre_coletas`): um vídeo tem menos comentários que a execução
    inteira, e exigir dele o mesmo mínimo silenciaria a regra sempre.

    Ordem da saída: maior piora primeiro. É o que a tela mostra no topo, e é o
    que a PME precisa ver antes.
    """
    ordenadas = ordenar_execucoes(execucoes)
    fatos: list[Fato] = []

    for antes, depois in pairwise(ordenadas):
        indice_antes = _videos_por_youtube_id(antes)
        for youtube_video_id, video_depois in _videos_por_youtube_id(depois).items():
            video_antes = indice_antes.get(youtube_video_id)
            if video_antes is None:
                continue
            if (
                video_antes.distribuicao.total < config.minimo_video_entre_coletas
                or video_depois.distribuicao.total < config.minimo_video_entre_coletas
            ):
                continue

            comparacao = comparar_proporcoes(
                positivos_antes=video_antes.distribuicao.negativo,
                tamanho_antes=video_antes.distribuicao.total,
                positivos_depois=video_depois.distribuicao.negativo,
                tamanho_depois=video_depois.distribuicao.total,
                z=config.z_confianca,
            )
            if not comparacao.significativa:
                continue

            fatos.append(
                _montar(
                    TipoFato.EVOLUCAO_DO_VIDEO,
                    {
                        # O título da coleta mais recente: um vídeo renomeado no
                        # YouTube deve aparecer com o nome que tem hoje.
                        "titulo": video_depois.titulo,
                        "youtube_video_id": youtube_video_id,
                        "percentual_negativo_antes": pontos_percentuais(comparacao.proporcao_antes),
                        "percentual_negativo_depois": pontos_percentuais(
                            comparacao.proporcao_depois
                        ),
                        "diferenca_em_pontos": pontos_percentuais(comparacao.diferenca),
                        "margem_em_pontos": pontos_percentuais(comparacao.margem),
                        "comentarios_antes": comparacao.tamanho_antes,
                        "comentarios_depois": comparacao.tamanho_depois,
                        "id_execucao_antes": antes.id_execucao,
                        "id_execucao_depois": depois.id_execucao,
                    },
                    Amostra(
                        tamanho=min(comparacao.tamanho_antes, comparacao.tamanho_depois),
                        minimo_exigido=config.minimo_video_entre_coletas,
                    ),
                    Origem(
                        id_execucoes=(antes.id_execucao, depois.id_execucao),
                        id_video=video_depois.id_video,
                        youtube_video_id=youtube_video_id,
                    ),
                )
            )

    fatos.sort(key=lambda fato: -float(fato.valores["diferenca_em_pontos"] or 0.0))
    return fatos


def fatos_da_campanha(
    execucoes: tuple[AgregadosExecucao, ...], config: ConfiguracaoInsights = PADRAO
) -> list[Fato]:
    """Todos os fatos que só existem comparando coletas do mesmo modelo.

    Levanta `ValueError` se as execuções não forem do mesmo `id_modelo`: comparar
    campanhas diferentes produziria uma frase sintaticamente correta sobre nada,
    e o erro seria invisível na tela. Uma lista vazia ou de uma execução só é
    entrada VÁLIDA — devolve `[]`, porque campanha de uma coleta não tem
    evolução.
    """
    modelos = {execucao.id_modelo for execucao in execucoes}
    if len(modelos) > 1:
        raise ValueError(
            f"fatos_da_campanha recebeu execucoes de modelos diferentes: {sorted(modelos)}. "
            "Uma campanha e a sequencia de coletas de UM modelo de analise."
        )
    if len(execucoes) < 2:
        return []

    return [*variacao_de_sentimento(execucoes, config), *evolucao_dos_videos(execucoes, config)]
