"""Estatística de concordância entre avaliadores — Fleiss, Cohen e voto majoritário.

Funções **puras**, sem banco e sem planilha: recebem rótulos, devolvem números. O
que lê arquivo e grava no Postgres mora em `calcular_concordancia.py`. A separação
existe para que a matemática que vai ser defendida na banca seja testável com dados
sintéticos, sem depender das planilhas reais terem voltado.

**Por que dois Kappas.** O Kappa de Cohen é definido para DOIS avaliadores; o projeto
tem três. O número principal é o **Fleiss**, que é a generalização para n avaliadores.
O Cohen entra par a par (1x2, 1x3, 2x3) para responder outra pergunta: *um avaliador
está destoando dos outros dois?* — algo que o Fleiss, sendo um número só, esconde.

Nenhuma biblioteca de estatística é usada de propósito. As duas fórmulas cabem em
vinte linhas, e escrever à mão é o que permite mostrar a conta na banca em vez de
apontar para uma chamada de `sklearn`.

Referências:
  Fleiss, J. L. (1971). Measuring nominal scale agreement among many raters.
  Cohen, J. (1960). A coefficient of agreement for nominal scales.
  Landis, J. R.; Koch, G. G. (1977). The measurement of observer agreement.
"""

from collections import Counter
from collections.abc import Sequence

# Faixas de Landis e Koch (1977). São a leitura convencional do Kappa e é por elas
# que a meta de κ >= 0,60 do manual se chama "substancial".
FAIXAS_LANDIS_KOCH = (
    (0.00, "pobre"),
    (0.20, "leve"),
    (0.40, "razoavel"),
    (0.60, "moderada"),
    (0.80, "substancial"),
    (1.01, "quase perfeita"),
)

# Meta do projeto (manual de rotulagem, Secao 1). Abaixo disto o gabarito nao vale
# e a amostra e refeita — nao e um aviso, e um porta o de decisao.
META_KAPPA = 0.60


class ConcordanciaDegenerada(ValueError):
    """Kappa indefinido: não há variação suficiente para calcular o acaso.

    Acontece quando a concordância esperada por acaso é 1,0 — isto é, quando todo
    mundo marcou a mesma classe em tudo. Aí `1 - P_e` é zero e a divisão não existe.
    Não é um caso raro de laboratório: se a amostra vier quase toda "neutro", é
    exatamente isto que acontece. Estourar é melhor que devolver 0,0, que seria lido
    como "os avaliadores discordaram" quando na verdade eles concordaram em tudo.
    """


def classificar_landis_koch(kappa: float) -> str:
    """Nome da faixa de concordância a que um Kappa pertence."""
    for limite, nome in FAIXAS_LANDIS_KOCH:
        if kappa < limite:
            return nome
    return "quase perfeita"


def matriz_de_contagem(
    votos_por_item: Sequence[Sequence[str]],
    classes: Sequence[str],
) -> list[tuple[int, ...]]:
    """Converte votos em `n_ij`: quantos avaliadores puseram o item *i* na classe *j*.

    É a forma que o Fleiss consome. Note que ela **perde a identidade do avaliador**
    de propósito — o Fleiss não pergunta quem votou o quê, só quantos votaram em cada
    classe. É por isso que ele não detecta um avaliador enviesado, e o Cohen par a par
    precisa existir ao lado dele.
    """
    indice = {classe: posicao for posicao, classe in enumerate(classes)}
    matriz: list[tuple[int, ...]] = []
    for votos in votos_por_item:
        linha = [0] * len(classes)
        for voto in votos:
            linha[indice[voto]] += 1
        matriz.append(tuple(linha))
    return matriz


def kappa_fleiss(contagens: Sequence[Sequence[int]]) -> float:
    """Kappa de Fleiss sobre a matriz `n_ij` de `matriz_de_contagem`.

        P_i   = (somatorio_j n_ij^2 - n) / (n * (n - 1))     concordancia dentro do item i
        P_bar = media dos P_i                                 concordancia observada
        p_j   = somatorio_i n_ij / (N * n)                    proporcao geral da classe j
        P_e   = somatorio_j p_j^2                             concordancia esperada por acaso
        kappa = (P_bar - P_e) / (1 - P_e)

    Exige o mesmo número de avaliadores em todos os itens — o que o validador garante
    antes de chegar aqui, recusando linha vazia. A fórmula geral de Fleiss admite `n`
    variável, mas aceitar isso aqui esconderia uma planilha entregue pela metade.
    """
    if not contagens:
        raise ValueError("matriz de contagem vazia")

    total_itens = len(contagens)
    avaliadores = sum(contagens[0])
    if avaliadores < 2:
        raise ValueError("Kappa exige ao menos 2 avaliadores por item")
    for posicao, linha in enumerate(contagens):
        if sum(linha) != avaliadores:
            raise ValueError(
                f"item {posicao} tem {sum(linha)} votos, mas o primeiro tem {avaliadores}; "
                "todos os itens precisam do mesmo numero de avaliadores"
            )

    concordancia_observada = sum(
        (sum(contagem * contagem for contagem in linha) - avaliadores)
        / (avaliadores * (avaliadores - 1))
        for linha in contagens
    ) / total_itens

    proporcoes = [
        sum(linha[coluna] for linha in contagens) / (total_itens * avaliadores)
        for coluna in range(len(contagens[0]))
    ]
    concordancia_esperada = sum(proporcao * proporcao for proporcao in proporcoes)

    if abs(1.0 - concordancia_esperada) < 1e-12:
        raise ConcordanciaDegenerada(
            "todos os avaliadores usaram uma unica classe em todos os itens: "
            "a concordancia esperada por acaso e 1,0 e o Kappa fica indefinido"
        )
    return (concordancia_observada - concordancia_esperada) / (1.0 - concordancia_esperada)


def kappa_fleiss_por_classe(
    contagens: Sequence[Sequence[int]],
    classes: Sequence[str],
) -> dict[str, float]:
    """Kappa de Fleiss de cada classe contra todas as outras (um-contra-resto).

    Responde "ONDE os avaliadores divergem", que o número global não responde. Um
    Fleiss geral de 0,62 com `negativo` em 0,31 quer dizer que o manual resolve bem
    positivo e neutro e deixa o negativo sem régua — e é esse o diagnóstico que a
    Seção 9 do manual pede antes de escrever a v2.

        kappa_j = 1 - somatorio_i [ n_ij * (n - n_ij) ]
                      / ( N * n * (n - 1) * p_j * (1 - p_j) )

    Classe que ninguém usou (ou que todos usaram sempre) fica de fora: `p_j * (1-p_j)`
    é zero e o Kappa dela é indefinido pelo mesmo motivo do caso degenerado.
    """
    total_itens = len(contagens)
    avaliadores = sum(contagens[0])
    resultado: dict[str, float] = {}

    for coluna, classe in enumerate(classes):
        proporcao = sum(linha[coluna] for linha in contagens) / (total_itens * avaliadores)
        denominador = total_itens * avaliadores * (avaliadores - 1) * proporcao * (1 - proporcao)
        if abs(denominador) < 1e-12:
            continue
        discordancia = sum(
            linha[coluna] * (avaliadores - linha[coluna]) for linha in contagens
        )
        resultado[classe] = 1.0 - discordancia / denominador
    return resultado


def kappa_cohen(rotulos_a: Sequence[str], rotulos_b: Sequence[str]) -> float:
    """Kappa de Cohen entre dois avaliadores, sobre listas alinhadas item a item.

        p_o   = proporcao de itens em que os dois marcaram igual
        p_e   = somatorio_j ( proporcao de j em A * proporcao de j em B )
        kappa = (p_o - p_e) / (1 - p_e)

    O alinhamento é responsabilidade de quem chama: as três planilhas saem em ordens
    diferentes de propósito, então as listas têm que vir ordenadas pelo mesmo critério
    (`id_comentario`), nunca por posição de linha.
    """
    if len(rotulos_a) != len(rotulos_b):
        raise ValueError(
            f"listas de tamanhos diferentes: {len(rotulos_a)} e {len(rotulos_b)}; "
            "os rotulos precisam estar alinhados por id_comentario"
        )
    if not rotulos_a:
        raise ValueError("listas de rotulos vazias")

    total = len(rotulos_a)
    observada = sum(1 for a, b in zip(rotulos_a, rotulos_b, strict=True) if a == b) / total

    contagem_a = Counter(rotulos_a)
    contagem_b = Counter(rotulos_b)
    esperada = sum(
        (contagem_a[classe] / total) * (contagem_b[classe] / total)
        for classe in set(contagem_a) | set(contagem_b)
    )

    if abs(1.0 - esperada) < 1e-12:
        raise ConcordanciaDegenerada(
            "os dois avaliadores usaram uma unica classe em todos os itens: "
            "a concordancia esperada por acaso e 1,0 e o Kappa fica indefinido"
        )
    return (observada - esperada) / (1.0 - esperada)


def matriz_confusao(
    rotulos_a: Sequence[str],
    rotulos_b: Sequence[str],
    classes: Sequence[str],
) -> dict[str, dict[str, int]]:
    """Quantas vezes A marcou `linha` enquanto B marcou `coluna`.

    A diagonal é a concordância; o que está fora dela é o mapa das divergências.
    """
    matriz = {linha: dict.fromkeys(classes, 0) for linha in classes}
    for a, b in zip(rotulos_a, rotulos_b, strict=True):
        matriz[a][b] += 1
    return matriz


def matriz_divergencia(
    rotulos_por_avaliador: Sequence[Sequence[str]],
    classes: Sequence[str],
) -> dict[str, dict[str, int]]:
    """Soma simétrica das confusões de todos os pares — o mapa `neutro x negativo`.

    Simétrica porque, com três avaliadores anônimos entre si, "A disse neutro e B
    disse negativo" e o inverso são o mesmo fato: o par de classes que a régua não
    separa. Cada par de classes aparece nas duas células.
    """
    matriz = {linha: dict.fromkeys(classes, 0) for linha in classes}
    quantidade = len(rotulos_por_avaliador)
    for primeiro in range(quantidade):
        for segundo in range(primeiro + 1, quantidade):
            for a, b in zip(
                rotulos_por_avaliador[primeiro],
                rotulos_por_avaliador[segundo],
                strict=True,
            ):
                matriz[a][b] += 1
                if a != b:
                    matriz[b][a] += 1
    return matriz


def voto_majoritario(votos: Sequence[str]) -> str | None:
    """Rótulo da maioria, ou `None` quando não há maioria.

    Com três avaliadores e três classes só existem três desfechos: 3-0 (unânime),
    2-1 (maioria) e 1-1-1 (empate total). `None` é o empate total, que a Seção 9 do
    manual manda levar para a reunião de consenso — nunca desempatar por sorteio nem
    pela ordem dos avaliadores, que embutiria no gabarito a opinião de quem por acaso
    ficou em primeiro.
    """
    if not votos:
        raise ValueError("nenhum voto")
    contagem = Counter(votos)
    mais_votado, quantidade = contagem.most_common(1)[0]
    empatados = [classe for classe, vezes in contagem.items() if vezes == quantidade]
    return mais_votado if len(empatados) == 1 else None
