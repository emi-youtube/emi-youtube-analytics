"""Conversão de emoji para texto em português.

Motivo (medido no corpus da Sprint 1): o vocabulário do BERTimbau tem 29.794
tokens e **nenhum emoji**. As 2.385 ocorrências de emoji do corpus viravam
`[UNK]` — 100% delas — e emoji consecutivos ainda colapsavam num `[UNK]` só.
Como 25,7% dos comentários têm emoji, e emoji é o sinal de sentimento mais direto
que existe em comentário de YouTube, deixar como estava era jogar fora um quarto
do sinal do corpus.

Estratégia em duas camadas:

1. `MAPA_EMOJI` — tradução curada dos emoji mais frequentes do corpus, escolhida
   para preservar o SENTIMENTO, não o desenho: 😂 vira "risos", não "rosto com
   lágrimas de alegria". As palavras foram escolhidas entre as que o vocabulário
   do BERTimbau já conhece, senão a conversão só trocaria um `[UNK]` por outro.
2. `_classificar` — regra automática para a cauda longa, por nome Unicode. Não
   traduz: rotula grosseiramente (rosto, coração, mão, bandeira...). Preserva
   "havia um emoji aqui, desta família" em vez de perder o token.

Caracteres invisíveis (seletor de variação, modificador de tom de pele, ZWJ) são
REMOVIDOS, não traduzidos: sozinhos não querem dizer nada e só poluiriam o texto.
No corpus eles eram 191 das 2.385 ocorrências.
"""

import re
import unicodedata

# Sequências de mais de um caractere, resolvidas antes dos emoji isolados.
# 🇧🇷 chega como dois indicadores regionais (U+1F1E7 U+1F1F7) e só faz sentido junto.
MAPA_SEQUENCIAS: dict[str, str] = {
    "\U0001f1e7\U0001f1f7": "bandeira do Brasil",
    "\U0001f1f5\U0001f1f9": "bandeira de Portugal",
    "\U0001f1fa\U0001f1f8": "bandeira dos Estados Unidos",
}

# Curado a partir da frequência real do corpus da Sprint 1 (execução 4).
# Ao acrescentar entradas, suba a VERSAO do pacote: o model_card.json registra
# com qual versão o modelo foi treinado.
MAPA_EMOJI: dict[str, str] = {
    # --- riso ---
    "\U0001f602": "risos",  # 😂
    "\U0001f923": "risos",  # 🤣
    "\U0001f605": "risos",  # 😅
    "\U0001f606": "risos",  # 😆
    "\U0001f600": "risos",  # 😀
    "\U0001f603": "risos",  # 😃
    "\U0001f604": "risos",  # 😄
    # --- afeto / aprovação ---
    "❤": "coração",  # ❤
    "\U0001f499": "coração",  # 💙
    "\U0001f493": "coração",  # 💓
    "\U0001f495": "coração",  # 💕
    "\U0001f60d": "amei",  # 😍
    "\U0001f970": "amei",  # 🥰
    "\U0001f60a": "sorriso",  # 😊
    "\U0001f929": "maravilhoso",  # 🤩
    "\U0001f44f": "aplausos",  # 👏
    "\U0001f44d": "positivo",  # 👍
    "\U0001f64f": "por favor",  # 🙏
    "\U0001f389": "comemoração",  # 🎉
    "\U0001f525": "fogo",  # 🔥
    "✅": "certo",  # ✅
    "\U0001f60e": "estiloso",  # 😎
    # --- negativo ---
    "\U0001f44e": "negativo",  # 👎
    "\U0001f622": "choro",  # 😢
    "\U0001f62d": "choro",  # 😭
    "\U0001f979": "choro",  # 🥹
    "\U0001f620": "raiva",  # 😠
    "\U0001f621": "raiva",  # 😡
    "\U0001f926": "decepção",  # 🤦
    "\U0001f4a9": "lixo",  # 💩
    "☠": "morte",  # ☠
    "\U0001f480": "morte",  # 💀
    # --- reação / outros frequentes ---
    "\U0001f62e": "espanto",  # 😮
    "\U0001f62f": "espanto",  # 😯
    "\U0001f914": "dúvida",  # 🤔
    "\U0001f4bf": "disco",  # 💿
    "\U0001f4c0": "disco",  # 📀
    "\U0001f964": "copo",  # 🥤
    "\U0001f514": "sino",  # 🔔
    "\U0001f515": "sino",  # 🔕
}

# Invisíveis ou modificadores: somem do texto.
# Escritos como `chr(...)` de propósito. Como literais eles seriam caracteres sem
# representação visível no meio do código — impossíveis de revisar, e o `ruff format`
# reescreve o escape `"️"` para o literal invisível na primeira formatação.
_DESCARTADOS = frozenset(
    {
        chr(0xFE0F),  # VARIATION SELECTOR-16 (apresentação emoji)
        chr(0xFE0E),  # VARIATION SELECTOR-15 (apresentação texto)
        chr(0x200D),  # ZERO WIDTH JOINER, que emenda emoji compostos
        chr(0x20E3),  # COMBINING ENCLOSING KEYCAP
    }
)

_INICIO_TOM_PELE, _FIM_TOM_PELE = 0x1F3FB, 0x1F3FF

_INICIO_INDICADOR, _FIM_INDICADOR = 0x1F1E6, 0x1F1FF

# Classificação da cauda longa, por palavra-chave do nome Unicode. A ordem importa:
# "SMILING FACE WITH HEART-SHAPED EYES" casa HEART antes de FACE, e "coração"
# carrega mais sentimento que "rosto".
_CLASSES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("HEART",), "coração"),
    (("FLAG",), "bandeira"),
    (("SKULL",), "morte"),
    (("FIRE",), "fogo"),
    (("STAR",), "estrela"),
    (("CLAPPING", "THUMBS", "HAND", "HANDS", "FINGER", "FIST", "PALM", "ARM"), "mão"),
    (("CAT", "DOG", "MONKEY", "ANIMAL"), "animal"),
    (("FACE", "SMILEY", "PERSON"), "rosto"),
)

# Usado quando o nome Unicode não resolve, ou quando o caractere nem tem nome nesta
# versão do Python (emoji novo). Preserva "havia um emoji aqui".
_GENERICO = "emoji"


def e_emoji(caractere: str) -> bool:
    """Heurística por categoria/intervalo Unicode, sem dependência externa."""
    if caractere in _DESCARTADOS:
        return True
    if unicodedata.category(caractere) == "So":
        return True
    ponto = ord(caractere)
    return any(
        inicio <= ponto <= fim
        for inicio, fim in (
            (0x1F300, 0x1FAFF),  # pictogramas, emoticons, suplementos
            (_INICIO_INDICADOR, _FIM_INDICADOR),  # indicadores regionais (bandeiras)
            (0x2600, 0x27BF),  # símbolos diversos e dingbats
            (_INICIO_TOM_PELE, _FIM_TOM_PELE),  # modificadores de tom de pele
        )
    )


def _descartavel(caractere: str) -> bool:
    return caractere in _DESCARTADOS or (_INICIO_TOM_PELE <= ord(caractere) <= _FIM_TOM_PELE)


def _classificar(caractere: str) -> str:
    """Rótulo grosseiro para emoji fora do mapa curado, pelo nome Unicode.

    Casa por PALAVRA, não por substring: "ARM" dentro de "ALARM CLOCK" ou "FARM"
    faria um despertador virar "mão". A quebra ignora hífen de propósito, senão
    "HEART-SHAPED" não casaria com "HEART".
    """
    # `unicodedata.name` levanta ValueError em caractere sem nome — acontece com
    # emoji mais novo que a tabela Unicode embutida no Python.
    nome = unicodedata.name(caractere, "")
    if not nome:
        return _GENERICO
    palavras_do_nome = set(re.split(r"[^A-Z]+", nome))
    for palavras, rotulo in _CLASSES:
        if palavras_do_nome.intersection(palavras):
            return rotulo
    return _GENERICO


def converter_emoji(texto: str) -> str:
    """Troca emoji por texto em português, cercado de espaços.

    Os espaços importam: sem eles `top😂` viraria `toprisos`, uma palavra que o
    tokenizer quebraria de forma imprevisível. O espaço extra é colapsado depois,
    em `normalizar_espacos`.

    >>> converter_emoji("amei 😂😂")
    'amei  risos  risos '
    >>> converter_emoji("nota 10 🇧🇷")
    'nota 10  bandeira do Brasil '
    """
    if not texto:
        return texto

    # Sequências primeiro: 🇧🇷 só quer dizer "Brasil" com os dois caracteres juntos.
    for sequencia, traducao in MAPA_SEQUENCIAS.items():
        texto = texto.replace(sequencia, f" {traducao} ")

    partes: list[str] = []
    for caractere in texto:
        if _descartavel(caractere):
            continue
        if not e_emoji(caractere):
            partes.append(caractere)
            continue
        traducao = MAPA_EMOJI.get(caractere) or _classificar(caractere)
        partes.append(f" {traducao} ")

    return "".join(partes)
