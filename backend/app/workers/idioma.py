"""Só comentário em português entra na análise (escopo do Capítulo 1 do TCC).

O classificador foi treinado e avaliado só em português brasileiro. Um comentário em
espanhol ou inglês receberia um rótulo sem garantia nenhuma, e ainda poderia virar um
tema à parte ("jajaja", "love"). A coleta descarta esses comentários antes de gravar e
conta quantos saíram, como já faz com o termo de pesquisa (`workers/coleta.py`).

**O detector** é o py3langid, port do langid.py (LUI; BALDWIN, 2012): Naive Bayes
sobre n-gramas de bytes, modelo de 97 línguas em 4,5 MB, sem rede e sem GPU. Ele fica
restrito a cinco candidatas (`CANDIDATAS`), as línguas que de fato aparecem em
comentários de vídeos brasileiros; restringir melhora a decisão entre vizinhas como
português e espanhol. Carrega uma vez por processo, na primeira coleta, e ocupa cerca
de 70 MB.

**Na dúvida, o comentário fica.** Perder português por engano custa mais que deixar
passar um estrangeiro, então o descarte exige uma de duas condições:

1. a maior parte das letras é de alfabeto não latino (coreano, russo, árabe), o mesmo
   corte que a exportação do corpus já fazia (`ml/exportacao/exportar_corpus.py`);
2. o texto tem pelo menos `PALAVRAS_MINIMAS` palavras, a língua mais provável não é o
   português e a probabilidade dela é de pelo menos `CONFIANCA_MINIMA`.

Abaixo de três palavras ("kkkk", "top", "lol") não há sinal para decidir, e fica.

Numa amostra escrita para o teste (`tests/test_idioma.py`: 50 comentários informais em
português, 20 em espanhol e 15 em inglês), nenhum português foi descartado; saíram 17
dos 20 em espanhol e todos os 13 em inglês com três palavras ou mais.
"""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

PORTUGUES = "pt"
CANDIDATAS = (PORTUGUES, "es", "en", "it", "fr")
CONFIANCA_MINIMA = 0.8
PALAVRAS_MINIMAS = 3
# Abaixo disso não há letras suficientes para julgar o alfabeto ("ок", um emoji solto).
LETRAS_MINIMAS_ALFABETO = 3

# Duas letras ou mais, sem dígito: "q" e "5" não contam como palavra.
_PALAVRA = re.compile(r"[^\W\d_]{2,}")


@lru_cache(maxsize=1)
def _identificador():
    """O identificador do py3langid, restrito às candidatas. Carregado uma vez só."""
    import py3langid
    from py3langid.langid import MODEL_FILE, LanguageIdentifier

    caminho = Path(py3langid.__file__).parent / MODEL_FILE
    identificador = LanguageIdentifier.from_model_file(caminho, norm_probs=True)
    identificador.set_languages(list(CANDIDATAS))
    return identificador


def idioma_provavel(texto: str) -> tuple[str, float]:
    """(código ISO 639-1, probabilidade entre as candidatas)."""
    lingua, probabilidade = _identificador().classify(texto)
    return lingua, float(probabilidade)


def _alfabeto_nao_latino(texto: str) -> bool:
    letras = [caractere for caractere in texto if caractere.isalpha()]
    if len(letras) < LETRAS_MINIMAS_ALFABETO:
        return False
    latinas = sum(1 for letra in letras if unicodedata.name(letra, "").startswith("LATIN"))
    return latinas * 2 < len(letras)


def em_outro_idioma(texto: str) -> bool:
    """O comentário deve sair da análise por não estar em português?"""
    if _alfabeto_nao_latino(texto):
        return True
    if len(_PALAVRA.findall(texto)) < PALAVRAS_MINIMAS:
        return False
    lingua, probabilidade = idioma_provavel(texto)
    return lingua != PORTUGUES and probabilidade >= CONFIANCA_MINIMA


def aceitar(texto: str) -> bool:
    """O filtro que a coleta passa ao cliente do YouTube: `True` mantém o comentário."""
    return not em_outro_idioma(texto)
