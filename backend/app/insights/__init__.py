"""Motor de insights por regras — funções puras, sem banco e sem endpoint.

**O que é.** Recebe os agregados já contados de uma execução (ou de várias, do
mesmo modelo de análise) e devolve **fatos**: achados estruturados com tipo,
valores, amostra e origem, cada um acompanhado da frase que o descreve.

**O que NÃO é.** Não lê banco, não expõe rota, não chama LLM. Os workers de
inferência e de tópicos ainda não existem, então não há de onde ler os
agregados: quando existirem, o endpoint monta `AgregadosExecucao` a partir do
Postgres e chama `fatos_da_execucao`. Essa fronteira é o que permite testar as
regras — que são o que de fato pode errar aqui — sem subir banco nenhum.

**A promessa do pacote** é não afirmar mais do que os números sustentam. Três
mecanismos, e nenhum deles é opcional:

- **amostra mínima por afirmação** (`ConfiguracaoInsights`), porque o custo de
  um erro não é o mesmo em todas as regras;
- **margem de incerteza** nas comparações entre coletas (`estatistica.py`), que
  descarta em silêncio a diferença que uma amostragem diferente explicaria;
- **frase por template** (`frases.py`), determinística, sem afirmação de causa.

Uso:

    from app.insights import AgregadosExecucao, Distribuicao, fatos_da_execucao

    fatos = fatos_da_execucao(
        AgregadosExecucao(
            id_execucao=1,
            id_modelo=7,
            distribuicao=Distribuicao(positivo=400, neutro=300, negativo=300),
            temas=(...),
            videos=(...),
        )
    )

Para a campanha, `fatos_da_campanha` recebe a tupla de execuções de um MESMO
`id_modelo` e devolve o que só existe na comparação entre coletas.
"""

from app.insights.agregados import (
    AgregadosExecucao,
    Distribuicao,
    TemaAgregado,
    VideoAgregado,
)
from app.insights.campanha import (
    evolucao_dos_videos,
    fatos_da_campanha,
    variacao_de_sentimento,
)
from app.insights.configuracao import PADRAO, ConfiguracaoInsights
from app.insights.execucao import (
    concentracao_das_criticas,
    fatos_da_execucao,
    tema_mais_criticado,
    tema_melhor_recebido,
    videos_muito_negativos,
)
from app.insights.fatos import Amostra, Fato, Origem, TipoFato, Valor
from app.insights.frases import redigir
from app.insights.temas import ParDeTemas, casar_temas, jaccard

__all__ = [
    "PADRAO",
    "AgregadosExecucao",
    "Amostra",
    "ConfiguracaoInsights",
    "Distribuicao",
    "Fato",
    "Origem",
    "ParDeTemas",
    "TemaAgregado",
    "TipoFato",
    "Valor",
    "VideoAgregado",
    "casar_temas",
    "concentracao_das_criticas",
    "evolucao_dos_videos",
    "fatos_da_campanha",
    "fatos_da_execucao",
    "jaccard",
    "redigir",
    "tema_mais_criticado",
    "tema_melhor_recebido",
    "variacao_de_sentimento",
    "videos_muito_negativos",
]
