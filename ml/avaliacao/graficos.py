"""Figuras do Capítulo 5, em `matplotlib`. Nada de cálculo aqui — só desenho.

São figuras para **papel**: sem interatividade, 300 dpi, e legíveis num TCC que pode
acabar impresso em preto e branco. Daí as três decisões de forma:

- cor é do MÉTODO, fixa por nome (léxico é sempre o mesmo tom em todas as figuras,
  apareça ele ao lado de um método ou de três);
- cada método leva também uma **textura** (hachura) diferente, que é o que mantém as
  barras distinguíveis quando a cor vira cinza na impressora;
- a matriz de confusão usa **um tom só, claro para escuro** — magnitude é escala, não
  identidade, e arco-íris em matriz de confusão é o erro clássico.

A paleta dos métodos foi conferida (banda de luminosidade, piso de croma, separação
para daltonismo protan/deutan/tritan e contraste contra o papel) antes de entrar
aqui; os tons saem da linguagem visual do produto (`frontend/design/DESIGN.md`).

O import de `matplotlib` acontece só quando alguém chama `gerar_figuras` —
`avaliar.py` importa este módulo tardiamente para que `--sem-graficos` funcione em
máquina sem a biblioteca instalada.
"""

from collections.abc import Sequence
from pathlib import Path

from ml.avaliacao.avaliar import Avaliacao
from ml.config import CLASSES

# Cor POR MÉTODO, não por posição: o léxico não muda de tom porque o BERTimbau
# entrou na comparação. Método fora desta tabela cai na reserva, em ordem fixa —
# nunca uma cor gerada na hora.
COR_POR_METODO = {
    "lexico": "#B4471F",
    "léxico": "#B4471F",
    "gemini (rotulo_fraco)": "#3A6FA8",
    "gemini": "#3A6FA8",
    "bertimbau": "#8A6D12",
}
CORES_RESERVA = ("#5B4A9E", "#6B665C")

# Hachuras na mesma ordem das cores. É o que salva a figura impressa em cinza.
TEXTURAS = ("", "///", "...", "\\\\\\", "xxx")

TINTA = "#1C1B19"  # --ink
TINTA_SUAVE = "#6B665C"  # --ink-muted
PAPEL = "#FFFFFF"  # --surface
GRADE = "#E3E0D8"  # --border

# Rampa sequencial da matriz de confusão: um tom só, do papel ao azul escuro.
RAMPA_CONFUSAO = ("#FFFFFF", "#DCE5EF", "#9DB6D2", "#5B8CBE", "#2B5486")

DPI = 300


def cor_do_metodo(metodo: str, posicao: int) -> str:
    """Tom fixo do método, ou o da reserva quando o nome é novo."""
    chave = metodo.strip().lower()
    if chave in COR_POR_METODO:
        return COR_POR_METODO[chave]
    return CORES_RESERVA[posicao % len(CORES_RESERVA)]


def _preparar_eixo(eixo, titulo: str, rotulo_valor: str, recuo_titulo: int = 12) -> None:
    """Grade discreta, sem moldura: o dado é a única coisa escura na figura.

    `recuo_titulo` abre espaço para a legenda quando ela fica acima do eixo.
    """
    eixo.set_title(titulo, color=TINTA, fontsize=11, pad=recuo_titulo, loc="left")
    eixo.set_xlabel(rotulo_valor, color=TINTA_SUAVE, fontsize=9)
    eixo.tick_params(colors=TINTA_SUAVE, labelsize=9)
    for lado in ("top", "right"):
        eixo.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        eixo.spines[lado].set_color(GRADE)


def figura_f1_macro(avaliacoes: Sequence[Avaliacao], caminho: Path) -> None:
    """Figura 1: F1 macro por método, com o intervalo de 95% como barra de erro.

    É a figura da decisão. Barra horizontal porque o nome do método é texto e cabe
    inteiro à esquerda, sem rotação — rótulo girado é o segundo erro mais comum em
    figura de TCC.

    O valor vai escrito ao lado de cada barra: são poucas barras, e quem lê o
    capítulo impresso não tem como medir a barra contra o eixo.
    """
    import matplotlib

    matplotlib.use("Agg")  # sem servidor gráfico: o script roda em terminal
    import matplotlib.pyplot as grafico

    figura, eixo = grafico.subplots(figsize=(7.2, 1.1 + 0.6 * len(avaliacoes)))
    figura.patch.set_facecolor(PAPEL)
    eixo.set_facecolor(PAPEL)

    posicoes = range(len(avaliacoes))
    for posicao, avaliacao in enumerate(avaliacoes):
        valor = avaliacao.metricas.f1_macro
        intervalo = avaliacao.intervalos.get("macro")
        erro = (
            [[valor - intervalo[0]], [intervalo[1] - valor]] if intervalo else None
        )
        eixo.barh(
            posicao,
            valor,
            height=0.55,
            color=cor_do_metodo(avaliacao.metodo, posicao),
            hatch=TEXTURAS[posicao % len(TEXTURAS)],
            edgecolor=PAPEL,
            linewidth=1.5,
            xerr=erro,
            error_kw={"ecolor": TINTA, "capsize": 4, "elinewidth": 1.2},
        )
        texto = f"{valor:.3f}"
        if intervalo:
            texto += f"  [{intervalo[0]:.3f}; {intervalo[1]:.3f}]"
        eixo.text(
            (intervalo[1] if intervalo else valor) + 0.02,
            posicao,
            texto,
            va="center",
            color=TINTA,
            fontsize=9,
        )

    eixo.set_yticks(list(posicoes))
    eixo.set_yticklabels([avaliacao.metodo for avaliacao in avaliacoes], color=TINTA, fontsize=10)
    eixo.invert_yaxis()
    eixo.set_xlim(0, 1.45)
    eixo.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    eixo.xaxis.grid(True, color=GRADE, linewidth=0.8)
    eixo.set_axisbelow(True)
    _preparar_eixo(eixo, "F1 macro por metodo (IC 95%, bootstrap)", "F1 macro")

    figura.tight_layout()
    figura.savefig(caminho, dpi=DPI, facecolor=PAPEL)
    grafico.close(figura)


def figura_f1_por_classe(avaliacoes: Sequence[Avaliacao], caminho: Path) -> None:
    """Figura 2: F1 de cada classe, método a método, com IC 95%.

    É a figura que responde *onde* um método falha — a mesma pergunta que o Kappa por
    classe responde sobre os avaliadores. Um F1 macro razoável pode esconder um
    `negativo` em 0,30, e é justamente o negativo que a PME precisa enxergar.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as grafico

    figura, eixo = grafico.subplots(figsize=(7.2, 4.2))
    figura.patch.set_facecolor(PAPEL)
    eixo.set_facecolor(PAPEL)

    quantidade = len(avaliacoes)
    largura = 0.8 / quantidade

    for posicao, avaliacao in enumerate(avaliacoes):
        centros = [
            indice + (posicao - (quantidade - 1) / 2) * largura
            for indice in range(len(CLASSES))
        ]
        valores = [avaliacao.metricas.por_classe[classe].f1 for classe in CLASSES]
        erros_baixo: list[float] = []
        erros_cima: list[float] = []
        for classe, valor in zip(CLASSES, valores, strict=True):
            intervalo = avaliacao.intervalos.get(classe)
            erros_baixo.append(valor - intervalo[0] if intervalo else 0.0)
            erros_cima.append(intervalo[1] - valor if intervalo else 0.0)

        eixo.bar(
            centros,
            valores,
            width=largura * 0.9,  # a folga é o espaçador de 2px entre barras vizinhas
            label=avaliacao.metodo,
            color=cor_do_metodo(avaliacao.metodo, posicao),
            hatch=TEXTURAS[posicao % len(TEXTURAS)],
            edgecolor=PAPEL,
            linewidth=1.2,
            yerr=[erros_baixo, erros_cima],
            error_kw={"ecolor": TINTA, "capsize": 3, "elinewidth": 1.0},
        )

    eixo.set_xticks(range(len(CLASSES)))
    eixo.set_xticklabels(list(CLASSES), color=TINTA, fontsize=10)
    eixo.set_ylim(0, 1.08)
    eixo.yaxis.grid(True, color=GRADE, linewidth=0.8)
    eixo.set_axisbelow(True)
    _preparar_eixo(eixo, "F1 por classe (IC 95%, bootstrap)", "", recuo_titulo=34)
    eixo.set_ylabel("F1", color=TINTA_SUAVE, fontsize=9)

    # Legenda ACIMA do eixo: dentro dela disputaria espaço com a barra mais alta
    # assim que um terceiro método entrar.
    legenda = eixo.legend(
        frameon=False,
        fontsize=9,
        loc="lower left",
        bbox_to_anchor=(0, 1.02),
        ncol=min(len(avaliacoes), 3),
    )
    for texto in legenda.get_texts():
        texto.set_color(TINTA)  # o texto é tinta; a cor da identidade está no marcador

    figura.tight_layout()
    figura.savefig(caminho, dpi=DPI, facecolor=PAPEL)
    grafico.close(figura)


def figura_confusao(avaliacao: Avaliacao, caminho: Path) -> None:
    """Figura 3+: matriz de confusão 3x3 de um método, em tom único.

    Linha = gabarito humano, coluna = previsão — a mesma convenção da matriz da
    concordância. A diagonal é o acerto; o que está fora dela é o mapa do erro, e é
    daí que sai a frase do capítulo sobre `neutro` x `negativo`.

    A intensidade é normalizada por LINHA (proporção dentro da classe verdadeira),
    senão a classe mais frequente pintaria a matriz inteira e as outras duas sumiriam.
    O número escrito em cada célula continua sendo a contagem absoluta.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as grafico
    from matplotlib.colors import LinearSegmentedColormap

    rampa = LinearSegmentedColormap.from_list("emi_sequencial", RAMPA_CONFUSAO)

    contagens = [
        [avaliacao.metricas.confusao[linha][coluna] for coluna in CLASSES] for linha in CLASSES
    ]
    proporcoes = [
        [celula / soma if (soma := sum(linha)) else 0.0 for celula in linha] for linha in contagens
    ]

    figura, eixo = grafico.subplots(figsize=(4.8, 4.4))
    figura.patch.set_facecolor(PAPEL)
    eixo.imshow(proporcoes, cmap=rampa, vmin=0.0, vmax=1.0)

    for indice_linha, linha in enumerate(contagens):
        for indice_coluna, celula in enumerate(linha):
            proporcao = proporcoes[indice_linha][indice_coluna]
            eixo.text(
                indice_coluna,
                indice_linha,
                f"{celula}\n{proporcao:.0%}",
                ha="center",
                va="center",
                fontsize=10,
                # Texto claro só onde a célula ficou escura demais para tinta.
                color=PAPEL if proporcao > 0.55 else TINTA,
            )

    # Fio de papel entre as células: sem ele dois tons vizinhos encostam e a matriz
    # vira um bloco só.
    for limite in range(len(CLASSES) - 1):
        eixo.axhline(limite + 0.5, color=PAPEL, linewidth=2)
        eixo.axvline(limite + 0.5, color=PAPEL, linewidth=2)

    eixo.set_xticks(range(len(CLASSES)))
    eixo.set_xticklabels(list(CLASSES), color=TINTA, fontsize=9)
    eixo.set_yticks(range(len(CLASSES)))
    eixo.set_yticklabels(list(CLASSES), color=TINTA, fontsize=9)
    eixo.set_xlabel("previsto", color=TINTA_SUAVE, fontsize=9)
    eixo.set_ylabel("gabarito humano", color=TINTA_SUAVE, fontsize=9)
    eixo.set_title(f"Matriz de confusao - {avaliacao.metodo}", color=TINTA, fontsize=11, loc="left")
    for lado in eixo.spines.values():
        lado.set_visible(False)
    eixo.tick_params(length=0)

    figura.tight_layout()
    figura.savefig(caminho, dpi=DPI, facecolor=PAPEL)
    grafico.close(figura)


def _nome_de_arquivo(metodo: str) -> str:
    """Nome de método vira nome de arquivo sem espaço, parêntese nem acento."""
    limpo = [letra if letra.isalnum() else "_" for letra in metodo.lower()]
    return "".join(limpo).strip("_").replace("__", "_")


def gerar_figuras(avaliacoes: Sequence[Avaliacao], diretorio: Path) -> list[Path]:
    """Gera as figuras do capítulo e devolve os caminhos, na ordem em que entram nele."""
    diretorio.mkdir(parents=True, exist_ok=True)
    caminhos: list[Path] = []

    caminho = diretorio / "f1_macro.png"
    figura_f1_macro(avaliacoes, caminho)
    caminhos.append(caminho)

    caminho = diretorio / "f1_por_classe.png"
    figura_f1_por_classe(avaliacoes, caminho)
    caminhos.append(caminho)

    for avaliacao in avaliacoes:
        caminho = diretorio / f"confusao_{_nome_de_arquivo(avaliacao.metodo)}.png"
        figura_confusao(avaliacao, caminho)
        caminhos.append(caminho)

    return caminhos
