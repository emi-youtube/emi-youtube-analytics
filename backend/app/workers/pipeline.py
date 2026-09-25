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
# Tópicos vem DEPOIS da inferência, e não entre a coleta e ela, por uma razão de
# produto: classificar é o que a PME espera ver primeiro, e a modelagem de
# tópicos é a etapa mais cara das três. Pondo tópicos no fim, uma falha ali deixa
# a execução em `erro` com os sentimentos já gravados — o painel mostra a
# distribuição e avisa que o agrupamento não saiu. Na ordem inversa, uma falha na
# modelagem custaria também a classificação.
#
# As duas não dependem uma da outra: tópicos lê COMENTARIOS (texto), inferência
# escreve ANALISES_SENTIMENTO. A ordem é escolha, não obrigação.
PROXIMA_ETAPA: dict[str, str | None] = {
    TIPO_COLETA: TIPO_INFERENCIA,
    TIPO_INFERENCIA: TIPO_TOPICOS,
    TIPO_TOPICOS: None,
}


def proxima_etapa(tipo: str) -> str | None:
    """Tipo do job que sucede `tipo`, ou `None` se ele encerra a execução.

    Tipo fora da cadeia (um `topicos` enfileirado à mão antes de o worker existir)
    também devolve `None`: encerra a execução em vez de apontar para o vazio.
    """
    return PROXIMA_ETAPA.get(tipo)
