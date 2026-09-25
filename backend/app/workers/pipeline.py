"""A cadeia de etapas de uma execução, num lugar só.

Uma execução não é um job: é uma sequência deles. Cada etapa, ao concluir, publica a
seguinte **na mesma transação** em que se marca concluída; a última é quem marca a
EXECUCAO como `concluida`. Enquanto houver etapa pendente, a execução fica em
`processando` — que é o que o usuário vê no GET /execucoes (UC04).

Por que a mesma transação: uma etapa que se marcasse concluída e só depois publicasse
a próxima poderia morrer no meio. A execução ficaria `processando` para sempre, sem
job na fila para ninguém buscar — o mesmo raciocínio que faz o POST /execucoes criar
execução e job juntos (`services/execucao.py`).

Por que um mapa, e não a etapa seguinte escrita dentro de cada worker: acrescentar o
worker de tópicos é editar este dicionário. Espalhado pelos workers, cada um teria de
saber quem vem depois de si, e a ordem real só existiria na cabeça de quem escreveu.
"""

TIPO_COLETA = "coleta"
TIPO_INFERENCIA = "inferencia"
TIPO_TOPICOS = "topicos"

# `None` = fim da cadeia: esta etapa marca a execução como `concluida`.
#
# Quando o worker de tópicos existir, ele entra ENTRE os dois (tópicos precisa dos
# comentários, não dos rótulos), e a mudança é só aqui:
#
#     TIPO_COLETA: TIPO_TOPICOS,
#     TIPO_TOPICOS: TIPO_INFERENCIA,
#     TIPO_INFERENCIA: None,
#
# `TIPO_TOPICOS` já está declarado acima porque o CHECK de `jobs.tipo` já o aceita —
# o valor existe no banco desde a migration inicial, só não há worker que o consuma.
PROXIMA_ETAPA: dict[str, str | None] = {
    TIPO_COLETA: TIPO_INFERENCIA,
    TIPO_INFERENCIA: None,
}


def proxima_etapa(tipo: str) -> str | None:
    """Tipo do job que sucede `tipo`, ou `None` se ele encerra a execução.

    Tipo fora da cadeia (um `topicos` enfileirado à mão antes de o worker existir)
    também devolve `None`: encerra a execução em vez de apontar para o vazio.
    """
    return PROXIMA_ETAPA.get(tipo)
