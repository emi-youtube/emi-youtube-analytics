"""A margem de incerteza que separa "mudou" de "variou".

**O problema que isto resolve.** Duas coletas do mesmo modelo quase nunca dão a
mesma proporção de negativos, mesmo que nada tenha mudado no público: cada
coleta é uma amostra dos comentários daquele momento. Um motor que reportasse
toda diferença diria "a rejeição subiu" e "a rejeição caiu" alternadamente, para
sempre, e a primeira vez que a equipe conferisse e não encontrasse nada o
recurso inteiro perderia a credibilidade.

**O critério.** Comparar duas proporções independentes pelo intervalo de
confiança da diferença. A margem é

    z * raiz( p1(1-p1)/n1 + p2(1-p2)/n2 )

e só é fato a diferença que a excede em módulo. É o teste padrão para duas
proporções e é defensável em banca sem depender de biblioteca: são quatro
operações, e não um `scipy.stats` que ninguém abre.

**O que ele NÃO é.** Não é correção para múltiplas comparações. O motor compara
várias coisas (cada par de execuções, cada vídeo), e a 95% uma em vinte
comparações sem efeito real passa. Isso é aceitável aqui porque cada fato é
apresentado com a sua amostra e é verificável na tela — mas é uma limitação
consciente, e está escrita aqui para não ser descoberta como defeito depois.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Comparacao:
    """O resultado de comparar duas proporções.

    Guarda a margem junto da diferença porque a tela e o teste precisam das
    duas: a diferença é o que se reporta, a margem é o que justifica reportá-la.
    """

    proporcao_antes: float
    proporcao_depois: float
    tamanho_antes: int
    tamanho_depois: int
    margem: float

    @property
    def diferenca(self) -> float:
        """Positiva quando subiu de `antes` para `depois`."""
        return self.proporcao_depois - self.proporcao_antes

    @property
    def significativa(self) -> bool:
        """A diferença excede a margem de incerteza?

        Estritamente maior: diferença exatamente igual à margem fica de fora. O
        caso é de medida zero com float, mas o critério precisa ser um só para o
        teste de caso-limite ter resposta definida.
        """
        return abs(self.diferenca) > self.margem


def erro_padrao_da_proporcao(proporcao: float, tamanho: int) -> float:
    """raiz( p(1-p)/n ). Zero para amostra vazia — o chamador barra antes."""
    if tamanho <= 0:
        return 0.0
    return math.sqrt(max(proporcao * (1.0 - proporcao), 0.0) / tamanho)


def comparar_proporcoes(
    positivos_antes: int,
    tamanho_antes: int,
    positivos_depois: int,
    tamanho_depois: int,
    z: float,
) -> Comparacao:
    """Compara duas proporções independentes e devolve a margem junto.

    `positivos_*` é a contagem do que se está medindo (negativos, quando a
    pergunta é sobre rejeição) e `tamanho_*` é o total daquela coleta.

    Amostra vazia dá proporção 0 e margem 0 — combinação que tornaria qualquer
    diferença "significativa". Quem chama precisa exigir a amostra mínima ANTES
    (é o que `configuracao.minimo_variacao` faz); esta função não decide corte
    de amostra, só faz a conta.
    """
    proporcao_antes = positivos_antes / tamanho_antes if tamanho_antes else 0.0
    proporcao_depois = positivos_depois / tamanho_depois if tamanho_depois else 0.0
    margem = z * math.sqrt(
        erro_padrao_da_proporcao(proporcao_antes, tamanho_antes) ** 2
        + erro_padrao_da_proporcao(proporcao_depois, tamanho_depois) ** 2
    )
    return Comparacao(
        proporcao_antes=proporcao_antes,
        proporcao_depois=proporcao_depois,
        tamanho_antes=tamanho_antes,
        tamanho_depois=tamanho_depois,
        margem=margem,
    )


def pontos_percentuais(fracao: float) -> float:
    """Fração para pontos percentuais, arredondada a uma casa.

    Uma casa porque é o que a frase mostra, e o valor que vai no fato tem que
    ser o mesmo que o leitor lê — um `valores` com 12.3456 e um texto com "12,3"
    são duas versões do mesmo número, e alguém vai comparar as duas.
    """
    return round(fracao * 100.0, 1)
