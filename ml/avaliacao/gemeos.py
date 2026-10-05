"""Gêmeos: dois comentários com o mesmo texto, ou quase o mesmo.

Um comentário do teste que tem gêmeo no treino não mede generalização: o modelo viu
aquele texto, com um rótulo, durante o ajuste dos pesos. Este módulo diz QUEM tem
gêmeo, em dois níveis, e é a régua única de duas coisas:

- a **medição** do vazamento (`ml/avaliacao/vazamento.py`), que separa as métricas do
  teste em "com gêmeo" e "sem gêmeo";
- o **filtro** da rodada 2 do treino (`ml.treino.dados.remover_vazamento`), que tira
  os gêmeos antes de treinar.

Se as duas usassem critérios diferentes, a medição deixaria de descrever o que o
filtro removeu.

**Stdlib pura, de propósito.** O filtro roda no Colab, dentro do notebook, e o
ambiente do Colab instala só `ml/requirements-treino.txt`. Um `import sklearn` aqui
seria mais um pacote para o pino do notebook conferir — e a conta cabe em vinte linhas.

Os dois níveis:

1. **exato** — o mesmo texto depois de `normalizar`: minúsculas, sem acento, sem
   pontuação, sequências de letra repetida reduzidas a uma (`VAMOOOO` = `vamo`).
   Normaliza-se o `texto_modelo` (a saída de `preparar_texto`), porque é ele que o
   BERTimbau lê: dois comentários que só diferem no emoji escolhido para a mesma
   palavra chegam ao modelo iguais;
2. **quase** — não é exato, mas a similaridade de Jaccard entre os conjuntos de
   trigramas de caractere é ≥ `LIMIAR_QUASE` (0,8).

**Por que Jaccard de trigramas, e por que 0,8.** Jaccard sobre n-gramas de caractere
("shingles") é a medida clássica de quase-duplicata de texto (Broder, 1997) e não
depende de vocabulário nem de peso aprendido no corpus — o que um cosseno TF-IDF
dependeria, e aí o limiar mudaria de sentido conforme o corpus. Trigrama porque o
comentário típico é curto: com n maior, duas frases de três palavras quase não
compartilham n-grama nenhum. O limiar foi escolhido olhando a distribuição dos pares
deste corpus (o histograma vai no `resultado_vazamento.json`): de 0,8 para cima os
pares são a mesma frase com uma palavra repetida, cortada ou acrescentada ("Lindo" x
"Lindo lindo lindo", "que musica maravilhosa" x "Música maravilhosa"); entre 0,6 e
0,8 já aparecem frases diferentes com o mesmo assunto ("Como é o nome da música e quem
canta?" x "Como é o nome da musica ?"), e abaixo de 0,6 são outros comentários. 0,8 é
também o valor usual da literatura de deduplicação. Errar para cima é o lado barato:
um par que escapa do filtro custa pouco, um exemplo legítimo removido do treino é
dado perdido.
"""

import bisect
import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

LIMIAR_QUASE = 0.8
TAMANHO_NGRAMA = 3

NIVEL_EXATO = "exato"
NIVEL_QUASE = "quase"

_NAO_PALAVRA = re.compile(r"[\W_]+")
_LETRA_REPETIDA = re.compile(r"(\w)\1+")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, sem pontuação, letra repetida reduzida, espaço único.

    Reduz QUALQUER repetição (duas letras ou mais), e não só as de três: "carro" e
    "caro" passam a colidir, mas uma colisão dessas no comentário inteiro é
    improvável, e reduzir só a partir de três deixaria "kk" diferente de "kkk".

    >>> normalizar("VAMOOOO!! Ação, né?")
    'vamo acao ne'
    """
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(letra for letra in decomposto if not unicodedata.combining(letra))
    sem_pontuacao = _NAO_PALAVRA.sub(" ", sem_acento)
    return " ".join(_LETRA_REPETIDA.sub(r"\1", sem_pontuacao).split())


def ngramas(normalizado: str, tamanho: int = TAMANHO_NGRAMA) -> frozenset[str]:
    """Conjunto de n-gramas de caractere, com um espaço de borda de cada lado.

    A borda faz a primeira e a última letra contarem como as do meio: sem ela, "bom"
    teria um trigrama só e qualquer comparação com ele seria tudo ou nada.

    >>> sorted(ngramas("oi"))
    [' oi', 'oi ']
    """
    if not normalizado:
        return frozenset()
    bordado = f" {normalizado} "
    return frozenset(bordado[i : i + tamanho] for i in range(len(bordado) - tamanho + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """len(A & B) / len(A | B); 0,0 quando algum dos dois é vazio."""
    if not a or not b:
        return 0.0
    comum = len(a & b)
    return comum / (len(a) + len(b) - comum)


@dataclass(frozen=True)
class Gemeo:
    """O gêmeo mais parecido de um comentário, no outro conjunto."""

    id_comentario: int
    id_gemeo: int
    nivel: str
    similaridade: float


@dataclass(frozen=True)
class _Indexado:
    id_comentario: int
    normalizado: str
    gramas: frozenset[str]


def _indexar(textos: Sequence[tuple[int, str]]) -> list[_Indexado]:
    indexados = []
    for id_comentario, texto in textos:
        normalizado = normalizar(texto)
        indexados.append(_Indexado(id_comentario, normalizado, ngramas(normalizado)))
    return indexados


def buscar_gemeos(
    consulta: Sequence[tuple[int, str]],
    referencia: Sequence[tuple[int, str]],
    limiar: float = LIMIAR_QUASE,
) -> dict[int, Gemeo]:
    """Para cada `(id, texto)` da consulta, o gêmeo mais parecido na referência.

    Devolve só quem TEM gêmeo. O exato vence o quase; entre dois do mesmo nível vence
    a maior similaridade e, empatando, o menor id — a mesma entrada dá sempre a mesma
    saída. Um par com o mesmo `id_comentario` nos dois lados é ignorado: é o que
    permite procurar gêmeos de um conjunto dentro dele mesmo
    (`buscar_gemeos(treino, treino)`).

    Texto que normaliza para vazio não tem gêmeo: não há o que comparar.

    **Poda pelo tamanho.** Jaccard ≥ t exige min(|A|,|B|) / max(|A|,|B|) ≥ t, então só
    os candidatos com |B| entre t·|A| e |A|/t são comparados. É o que deixa o treino
    contra ele mesmo (1.870 x 1.870) em segundos, em Python puro.

    >>> buscar_gemeos([(1, "Que carro lindo!")], [(9, "que carro LINDO")])[1].nivel
    'exato'
    """
    if not 0 < limiar <= 1:
        raise ValueError(f"limiar deve ficar em (0, 1], veio {limiar}")

    referencias = sorted(_indexar(referencia), key=lambda item: len(item.gramas))
    tamanhos = [len(item.gramas) for item in referencias]
    por_texto: dict[str, list[int]] = defaultdict(list)
    for item in referencias:
        if item.normalizado:
            por_texto[item.normalizado].append(item.id_comentario)

    encontrados: dict[int, Gemeo] = {}
    for item in _indexar(consulta):
        if not item.normalizado:
            continue

        iguais = [
            id_ref for id_ref in por_texto.get(item.normalizado, []) if id_ref != item.id_comentario
        ]
        if iguais:
            encontrados[item.id_comentario] = Gemeo(
                item.id_comentario, min(iguais), NIVEL_EXATO, 1.0
            )
            continue

        tamanho = len(item.gramas)
        inicio = bisect.bisect_left(tamanhos, limiar * tamanho)
        fim = bisect.bisect_right(tamanhos, tamanho / limiar)
        melhor: Gemeo | None = None
        for candidato in referencias[inicio:fim]:
            if candidato.id_comentario == item.id_comentario:
                continue
            similaridade = jaccard(item.gramas, candidato.gramas)
            if similaridade < limiar:
                continue
            if (
                melhor is None
                or similaridade > melhor.similaridade
                or (
                    similaridade == melhor.similaridade
                    and candidato.id_comentario < melhor.id_gemeo
                )
            ):
                melhor = Gemeo(
                    item.id_comentario, candidato.id_comentario, NIVEL_QUASE, similaridade
                )
        if melhor is not None:
            encontrados[item.id_comentario] = melhor
    return encontrados
