"""Casar o mesmo assunto entre duas execuções — por palavra-chave, nunca por rótulo.

**Por que o rótulo não serve.** `TEMAS.rotulo_tema` é gerado por execução, por
LDA ou clustering sobre o corpus daquela coleta. Duas coletas do mesmo modelo
produzem agrupamentos parecidos com rótulos diferentes — "atendimento",
"suporte", "atendimento ao cliente" —, e a numeração dos tópicos não tem
significado nenhum entre rodadas: o tópico 3 de janeiro não é o tópico 3 de
março. Casar por rótulo produziria comparações entre assuntos distintos com
uma confiança que nada sustenta, e o erro seria invisível na tela, que mostraria
dois rótulos plausíveis lado a lado.

**O que serve.** As palavras-chave, que são o conteúdo do tópico. A medida é o
índice de Jaccard sobre os conjuntos normalizados:

    tamanho da intersecao / tamanho da uniao

Jaccard e não contagem crua de interseção porque um tema com 40 palavras-chave
cruzaria 4 palavras com quase qualquer outro; dividir pela união desconta o
tamanho. O limiar padrão é 0,3 — dois terços de divergência ainda casam, o que
é tolerante de propósito: o custo de não casar (perder a comparação) é maior que
o de casar errado (uma comparação que a amostra mínima e a margem de incerteza
ainda precisam aprovar antes de virar fato).

**Casamento é um-para-um e guloso.** Cada tema de uma coleta casa com no máximo
um da outra, na ordem do melhor Jaccard para o pior. Sem isso, um tema genérico
casaria com três específicos e apareceria três vezes na mesma lista de fatos.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.insights.agregados import TemaAgregado

LIMIAR_JACCARD_PADRAO = 0.3


def jaccard(uma: frozenset[str], outra: frozenset[str]) -> float:
    """Sobreposição de dois conjuntos, de 0 (nada em comum) a 1 (iguais).

    Dois conjuntos vazios devolvem 0,0 e não 1,0: "não sei as palavras-chave de
    nenhum dos dois" não é evidência de que são o mesmo assunto. É o caso de um
    worker de tópicos que não gravou `palavras_chave`, e ele precisa resultar em
    nenhum casamento, não em todos.
    """
    if not uma or not outra:
        return 0.0
    uniao = len(uma | outra)
    return len(uma & outra) / uniao if uniao else 0.0


@dataclass(frozen=True, slots=True)
class ParDeTemas:
    """O mesmo assunto, visto em duas execuções."""

    antes: TemaAgregado
    depois: TemaAgregado
    sobreposicao: float


def casar_temas(
    antes: tuple[TemaAgregado, ...],
    depois: tuple[TemaAgregado, ...],
    limiar: float = LIMIAR_JACCARD_PADRAO,
) -> list[ParDeTemas]:
    """Pares de temas que são o mesmo assunto, do mais parecido para o menos.

    Guloso e um-para-um: calcula todos os pares acima do limiar, ordena por
    sobreposição e vai fixando, pulando quem já casou. Não é o emparelhamento de
    peso máximo (que exigiria húngaro para um ganho que nenhum caso deste
    projeto justifica), mas é determinístico — e o desempate por `id_tema`
    garante que a mesma entrada produza sempre a mesma lista, o que um `set` na
    ordem de iteração não garantiria.
    """
    candidatos = []
    for tema_antes in antes:
        chaves_antes = tema_antes.chaves_normalizadas
        for tema_depois in depois:
            sobreposicao = jaccard(chaves_antes, tema_depois.chaves_normalizadas)
            if sobreposicao >= limiar:
                candidatos.append(
                    (sobreposicao, tema_antes.id_tema, tema_depois.id_tema, tema_antes, tema_depois)
                )
    # -sobreposicao para o maior vir primeiro; os ids desempatam para a saída
    # não depender da ordem de iteração das tuplas de entrada.
    candidatos.sort(key=lambda item: (-item[0], item[1], item[2]))

    usados_antes: set[int] = set()
    usados_depois: set[int] = set()
    pares: list[ParDeTemas] = []
    for sobreposicao, id_antes, id_depois, tema_antes, tema_depois in candidatos:
        if id_antes in usados_antes or id_depois in usados_depois:
            continue
        usados_antes.add(id_antes)
        usados_depois.add(id_depois)
        pares.append(ParDeTemas(antes=tema_antes, depois=tema_depois, sobreposicao=sobreposicao))
    return pares
