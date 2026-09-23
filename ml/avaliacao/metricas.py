"""Métricas de classificação — acurácia, precisão, revocação, F1 e bootstrap.

Funções **puras**, no mesmo espírito de `ml/concordancia/kappa.py`: recebem duas
listas de rótulos alinhadas, devolvem números. O que lê banco, CSV e desenha gráfico
mora em `avaliar.py` e `graficos.py`.

**Escritas à mão, de novo de propósito.** As fórmulas cabem em dez linhas e a banca
pode pedir a conta de qualquer célula. O `scikit-learn` entra só nos testes
(`ml/tests/test_avaliacao.py`), como conferência independente — a mesma estratégia
usada no Kappa, que é conferido contra os valores publicados de Fleiss (1971).

**F1 MACRO é a métrica do projeto** (CLAUDE.md regra 8). A acurácia é reportada
porque o Capítulo 5 a cita, não porque decide: num corpus 42,6% positivo, chutar
"positivo" em tudo já dá 42,6% de acurácia e F1 macro 0,20. A média macro trata as
três classes como igualmente importantes, que é a premissa do projeto — a PME
precisa enxergar o negativo, que é justamente a classe menos frequente.

Convenção de divisão por zero (a mesma do `scikit-learn` com `zero_division=0`):
precisão sem nenhuma previsão da classe, revocação sem nenhum exemplo da classe e
F1 com precisão e revocação zeradas valem 0,0. Vale para o bootstrap também.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

# A matriz de confusão é a mesma conta da concordância vista de outro ângulo: lá é
# "o avaliador A disse X e o B disse Y", aqui é "o gabarito diz X e o método previu
# Y". Reaproveitar em vez de reescrever mantém uma régua só — se a convenção de
# linha/coluna mudar, muda nos dois lugares de uma vez.
from ml.concordancia.kappa import matriz_confusao

__all__ = [
    "Metricas",
    "MetricasClasse",
    "acuracia",
    "avaliar_previsoes",
    "intervalo_bootstrap",
    "matriz_confusao",
    "percentil",
]

# Reamostragens do bootstrap. 2.000 é o suficiente para um intervalo percentil
# estável na terceira casa com n=334; subir para 10.000 muda o resultado na quarta.
REAMOSTRAGENS = 2000

# Semente do bootstrap. A MESMA do resto do pipeline (`ml.config.SEMENTE`), repetida
# aqui porque este módulo não importa `ml.config` — o intervalo publicado no TCC tem
# que sair igual em qualquer máquina que rode o script.
SEMENTE = 42

CONFIANCA = 0.95


@dataclass(frozen=True)
class MetricasClasse:
    """Precisão, revocação e F1 de UMA classe, com o que as produziu.

    `verdadeiros_positivos`, `falsos_positivos` e `falsos_negativos` viajam junto
    porque é com eles que se confere a conta na banca sem refazer o cálculo.
    """

    classe: str
    verdadeiros_positivos: int
    falsos_positivos: int
    falsos_negativos: int
    precisao: float
    revocacao: float
    f1: float
    suporte: int


@dataclass(frozen=True)
class Metricas:
    """O resultado completo de um método contra o gabarito."""

    total: int
    acuracia: float
    por_classe: dict[str, MetricasClasse]
    precisao_macro: float
    revocacao_macro: float
    f1_macro: float
    confusao: dict[str, dict[str, int]]


def _divisao_segura(numerador: float, denominador: float) -> float:
    """0,0 quando não há do que dividir — a convenção `zero_division=0`."""
    return numerador / denominador if denominador else 0.0


def acuracia(verdadeiros: Sequence[str], previstos: Sequence[str]) -> float:
    """Proporção de acertos. Reportada, nunca decisiva (ver docstring do módulo)."""
    _conferir_alinhamento(verdadeiros, previstos)
    return _divisao_segura(
        sum(1 for real, previsto in zip(verdadeiros, previstos, strict=True) if real == previsto),
        len(verdadeiros),
    )


def _conferir_alinhamento(verdadeiros: Sequence[str], previstos: Sequence[str]) -> None:
    """As duas listas precisam ter o mesmo tamanho e não ser vazias.

    O alinhamento item a item é responsabilidade de quem chama: `avaliar.py` ordena
    os dois lados por `id_comentario` antes de chegar aqui. Comparar por posição de
    linha alinharia comentários diferentes e a métrica mediria ruído.
    """
    if len(verdadeiros) != len(previstos):
        raise ValueError(
            f"listas de tamanhos diferentes: {len(verdadeiros)} e {len(previstos)}; "
            "gabarito e previsao precisam estar alinhados por id_comentario"
        )
    if not verdadeiros:
        raise ValueError("listas vazias: nao ha o que avaliar")


def avaliar_previsoes(
    verdadeiros: Sequence[str],
    previstos: Sequence[str],
    classes: Sequence[str],
) -> Metricas:
    """Calcula tudo de um método de uma vez.

        precisao_j  = VP_j / (VP_j + FP_j)      dos que previ como j, quantos eram j
        revocacao_j = VP_j / (VP_j + FN_j)      dos que eram j, quantos eu achei
        f1_j        = 2 * p * r / (p + r)       média harmônica das duas
        macro       = média aritmética simples das três classes

    A média macro NÃO é ponderada pelo suporte de propósito: ponderar devolveria o
    peso à classe majoritária e desfaria exatamente o que a regra 8 do CLAUDE.md
    pede.

    **O denominador é sempre 3**, as classes fechadas do projeto — inclusive quando
    uma delas não aparece na amostra. É aqui que a implementação diverge do PADRÃO do
    `scikit-learn`, que faz a média só sobre as classes presentes nos dados e portanto
    muda de denominador conforme a amostra. Dois métodos medidos com denominadores
    diferentes não seriam comparáveis, e comparar métodos é o que o Capítulo 5 faz.
    Quem refizer a conta na biblioteca precisa passar
    `labels=['positivo', 'negativo', 'neutro']` para chegar ao mesmo número
    (`ml/tests/test_avaliacao.py` trava as duas leituras).
    """
    _conferir_alinhamento(verdadeiros, previstos)

    confusao = matriz_confusao(verdadeiros, previstos, classes)
    por_classe: dict[str, MetricasClasse] = {}

    for classe in classes:
        verdadeiros_positivos = confusao[classe][classe]
        falsos_negativos = sum(confusao[classe][outra] for outra in classes) - verdadeiros_positivos
        falsos_positivos = sum(confusao[outra][classe] for outra in classes) - verdadeiros_positivos

        precisao = _divisao_segura(verdadeiros_positivos, verdadeiros_positivos + falsos_positivos)
        revocacao = _divisao_segura(verdadeiros_positivos, verdadeiros_positivos + falsos_negativos)
        f1 = _divisao_segura(2 * precisao * revocacao, precisao + revocacao)

        por_classe[classe] = MetricasClasse(
            classe=classe,
            verdadeiros_positivos=verdadeiros_positivos,
            falsos_positivos=falsos_positivos,
            falsos_negativos=falsos_negativos,
            precisao=precisao,
            revocacao=revocacao,
            f1=f1,
            suporte=verdadeiros_positivos + falsos_negativos,
        )

    quantidade = len(classes)
    return Metricas(
        total=len(verdadeiros),
        acuracia=acuracia(verdadeiros, previstos),
        por_classe=por_classe,
        precisao_macro=sum(m.precisao for m in por_classe.values()) / quantidade,
        revocacao_macro=sum(m.revocacao for m in por_classe.values()) / quantidade,
        f1_macro=sum(m.f1 for m in por_classe.values()) / quantidade,
        confusao=confusao,
    )


def percentil(valores: Sequence[float], fracao: float) -> float:
    """Percentil por interpolação linear entre as duas posições vizinhas.

    É o mesmo método do `numpy.percentile` padrão (`linear`), que é o que a
    literatura de bootstrap percentil assume. Escrito à mão pelo motivo de sempre:
    o módulo não carrega dependência de cálculo.

    >>> percentil([1, 2, 3, 4], 0.5)
    2.5
    """
    if not valores:
        raise ValueError("nenhum valor")
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return float(ordenados[0])

    posicao = fracao * (len(ordenados) - 1)
    abaixo = int(posicao)
    acima = min(abaixo + 1, len(ordenados) - 1)
    peso = posicao - abaixo
    return float(ordenados[abaixo] * (1 - peso) + ordenados[acima] * peso)


def _f1_de_uma_classe(
    verdadeiros: Sequence[str], previstos: Sequence[str], classe: str
) -> tuple[float, int]:
    """F1 de uma classe e o suporte dela — o núcleo barato do laço do bootstrap."""
    verdadeiros_positivos = falsos_positivos = falsos_negativos = 0
    for real, previsto in zip(verdadeiros, previstos, strict=True):
        if real == classe and previsto == classe:
            verdadeiros_positivos += 1
        elif previsto == classe:
            falsos_positivos += 1
        elif real == classe:
            falsos_negativos += 1

    precisao = _divisao_segura(verdadeiros_positivos, verdadeiros_positivos + falsos_positivos)
    revocacao = _divisao_segura(verdadeiros_positivos, verdadeiros_positivos + falsos_negativos)
    return (
        _divisao_segura(2 * precisao * revocacao, precisao + revocacao),
        verdadeiros_positivos + falsos_negativos,
    )


def intervalo_bootstrap(
    verdadeiros: Sequence[str],
    previstos: Sequence[str],
    classes: Sequence[str],
    reamostragens: int = REAMOSTRAGENS,
    semente: int = SEMENTE,
    confianca: float = CONFIANCA,
) -> dict[str, tuple[float, float]]:
    """Intervalo de confiança percentil do F1 de cada classe, e do F1 macro.

    O método é o bootstrap não paramétrico: sorteia com reposição `n` comentários do
    conjunto de teste, recalcula o F1, repete 2.000 vezes e toma os percentis 2,5 e
    97,5 da distribuição resultante.

    **Por que o Capítulo 5 precisa disso.** Com 334 comentários, um F1 macro de 0,71
    contra 0,68 não é diferença nenhuma — é a largura do intervalo. Publicar o número
    sozinho convida a banca a perguntar "e se fossem outros 334?", e a resposta certa
    é o intervalo, não um argumento. Ele também é o que sustenta a comparação
    léxico x BERTimbau: se os intervalos se sobrepõem, o ganho não está demonstrado.

    A chave `"macro"` entra junto das classes porque é o F1 macro que decide o gate
    da Sprint 1, e um intervalo só das classes deixaria justamente o número da
    decisão sem margem.

    Reamostragem em que a classe não aparece no gabarito sorteado é pulada: ali o F1
    daquela classe não é 0, é indefinido, e contar como 0 puxaria o limite inferior
    do intervalo para baixo por um artefato do sorteio. Com 334 comentários e ~1/3
    por classe isso praticamente não acontece — a guarda existe para a amostra
    pequena do teste sintético, onde acontece.
    """
    _conferir_alinhamento(verdadeiros, previstos)
    if reamostragens < 1:
        raise ValueError("bootstrap exige ao menos uma reamostragem")

    sorteio = random.Random(semente)
    total = len(verdadeiros)
    amostras: dict[str, list[float]] = {classe: [] for classe in classes}
    amostras["macro"] = []

    for _ in range(reamostragens):
        posicoes = [sorteio.randrange(total) for _ in range(total)]
        reais = [verdadeiros[posicao] for posicao in posicoes]
        preditos = [previstos[posicao] for posicao in posicoes]

        f1_da_vez: list[float] = []
        for classe in classes:
            f1, suporte = _f1_de_uma_classe(reais, preditos, classe)
            if not suporte:
                continue
            amostras[classe].append(f1)
            f1_da_vez.append(f1)
        if f1_da_vez:
            amostras["macro"].append(sum(f1_da_vez) / len(f1_da_vez))

    margem = (1 - confianca) / 2
    return {
        chave: (percentil(valores, margem), percentil(valores, 1 - margem))
        for chave, valores in amostras.items()
        if valores
    }
