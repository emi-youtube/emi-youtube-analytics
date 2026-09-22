"""Normalização de texto e a função de entrada do BERTimbau.

Duas funções, dois públicos (CLAUDE.md Seção 3, "Quem vê qual texto"):

- `normalizar_espacos` produz o texto **canônico**: é o que vai para o banco, para
  o avaliador humano e para a Gemini. Só arruma quebra de linha e espaço — nada que
  mude o que está escrito.
- `preparar_texto` produz o texto **do modelo**: canônico + normalização tipográfica
  + emoji convertido. Existe por limitação do tokenizer do BERTimbau e só é aplicado
  na entrada dele (montagem do dataset de treino e worker de inferência). É derivado,
  nunca canônico.

A separação importa porque rótulo tem que ser dado sobre o que a pessoa escreveu. Se
o avaliador humano lesse "risos" onde o usuário digitou 😂, ele estaria rotulando o
nosso pré-processamento, não o comentário.
"""

from preprocessamento.emoji import converter_emoji

# Trocas tipográficas: mesmo caractere, grafia que o vocabulário do BERTimbau conhece.
# Só entra aqui o que NÃO muda o que está escrito — trocar "…" por "..." é a mesma
# reticência; expandir "q" para "que" seria interpretar, e o CLAUDE.md proíbe
# (normalização semântica é trabalho do leitor, não do pipeline).
# Chaves como `chr(...)` pelo mesmo motivo dos invisíveis em `emoji.py`: o
# `ruff format` reescreve o escape para o literal, e o literal aqui é um caractere
# ambíguo (o ACUTE ACCENT é visualmente idêntico ao apóstrofo em muitas fontes).
SUBSTITUICOES_TIPOGRAFICAS: dict[str, str] = {
    chr(0x2026): "...",  # HORIZONTAL ELLIPSIS, o caractere unico de reticencias
    chr(0x00B4): "'",  # ACUTE ACCENT usado como apostrofo ("Assassin<acento>s")
}


def normalizar_espacos(texto: str) -> str:
    """Quebra de linha vira espaço e o espaço em excesso é colapsado.

    Esta é a ÚNICA transformação que o texto canônico sofre. A quebra de linha some
    por dois motivos: o corpus é exportado em CSV, onde um `\\n` cru no meio do campo
    corrompe o arquivo; e o BERT não usa a quebra como sinal.
    """
    return " ".join(texto.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").split())


def normalizar_tipografia(texto: str) -> str:
    """Troca variantes tipográficas pela grafia que o tokenizer conhece.

    >>> normalizar_tipografia("esperando…")
    'esperando...'
    >>> normalizar_tipografia("Assassin" + chr(0x00B4) + "s Creed")
    "Assassin's Creed"
    """
    for original, substituto in SUBSTITUICOES_TIPOGRAFICAS.items():
        texto = texto.replace(original, substituto)
    return texto


def preparar_texto(texto: str) -> str:
    """Pré-processamento da ENTRADA DO MODELO. Treino e inferência chamam esta.

    Não use para gravar no banco nem para mostrar a humano: para isso é
    `normalizar_espacos`.

    Ordem: tipografia, depois emoji, depois espaço. A conversão de emoji injeta
    espaços de propósito (`top😂` -> `top risos `), e é o passo final que limpa a
    sobra.

    >>> preparar_texto("  adorei\\n\\no produto 😂😂  ")
    'adorei o produto risos risos'
    >>> preparar_texto("   ")
    ''
    """
    if not texto:
        return ""
    return normalizar_espacos(converter_emoji(normalizar_tipografia(texto)))
