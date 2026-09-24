"""Normalização de palavra-chave — só para COMPARAR, nunca para exibir.

Isto não é o `preprocessamento/` do projeto e não deve virar um. Aquele pacote
existe por uma limitação do tokenizer do BERTimbau e se aplica só na entrada do
modelo (CLAUDE.md Seção 3). Aqui o problema é outro: decidir se a palavra-chave
"Preço" de uma coleta é a mesma coisa que "preco" de outra, para casar temas
entre execuções.

Por isso a normalização é mínima e reversível em intenção — caixa, acento e
espaço — e **o texto normalizado nunca aparece na tela**. A frase usa o
`rotulo_tema` original, como ele veio do worker de tópicos.

Acento é removido de propósito: o rótulo vem de pipeline automático sobre
comentário de YouTube, onde a mesma palavra aparece acentuada e não acentuada na
mesma execução. Tratar "preço" e "preco" como assuntos distintos criaria dois
temas onde há um, e o casamento entre coletas falharia justamente nos assuntos
mais falados.
"""

from __future__ import annotations

import unicodedata


def normalizar_palavra_chave(palavra: str) -> str:
    """Caixa baixa, sem acento, sem espaço nas pontas.

    Devolve string vazia para entrada que não sobra nada — o chamador descarta.

    >>> normalizar_palavra_chave("  Preço ")
    'preco'
    >>> normalizar_palavra_chave("ATENDIMENTO")
    'atendimento'
    >>> normalizar_palavra_chave("   ")
    ''
    """
    decomposta = unicodedata.normalize("NFKD", palavra.strip().casefold())
    return "".join(caractere for caractere in decomposta if not unicodedata.combining(caractere))
