"""Preparação do texto para a modelagem de tópicos — que NÃO é a do classificador.

São dois pré-processamentos diferentes de propósito, e a diferença é o ponto:

- **`preprocessamento.preparar_texto`** existe por limitação do tokenizer do
  BERTimbau, que não tem emoji no vocabulário. Ele CONVERTE emoji em palavra
  (😍 -> "amei") para o classificador enxergar o sentimento que o emoji carrega.
- **este módulo** existe para achar ASSUNTO. Emoji não é assunto: um tema
  chamado "risos, coração, amei" não diz à PME sobre o que o público está
  falando, diz com que humor está falando — que é justamente o que a outra
  metade do sistema já mede.

Por isso aqui o emoji é **removido**, não convertido, e a entrada é o texto
ORIGINAL do banco (CLAUDE.md Seção 3: o banco guarda o original; qualquer
derivação é derivação). Rodar `preparar_texto` antes disto injetaria as 23
palavras do mapa de emoji no vocabulário de tópicos.

Guarda dupla, porque uma só não basta: mesmo removendo o emoji, um comentário
pode trazer "risos" ou "coração" digitado à mão, e essas palavras herdariam a
frequência de milhares de emoji convertidos se algum dia a entrada mudar. As 23
palavras do `MAPA_EMOJI` entram na lista de stopwords, importadas de lá — não
copiadas —, então acrescentar um emoji ao mapa não abre um buraco aqui.
"""

import re
import unicodedata

from preprocessamento import MAPA_EMOJI

# URL inteira, com ou sem protocolo. Vem antes de tudo: um link sobrevive à
# remoção de pontuação como um punhado de tokens ("https", "com", "watch").
URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)

# Menção (@canal) e a marca de resposta que o YouTube injeta no início.
MENCAO = re.compile(r"@[\w.\-]+")

# Timestamps ("2:35", "01:02:03") — frequentes em comentário de vídeo e sem
# nenhum valor de assunto.
TIMESTAMP = re.compile(r"\b\d{1,2}(?::\d{2}){1,2}\b")

# Palavra: letras com acento, hífen interno permitido. Dígito fica de fora —
# "2024" e "10x" não são assunto, e número solto vira ruído de alta frequência.
PALAVRA = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)

# Comprimento mínimo de token. "de", "e", "ja" caem nas stopwords; este corte
# pega o resto do lixo de uma letra e as siglas que sobram da limpeza.
MIN_CARACTERES_TOKEN = 3

# Riso, com qualquer número de repetições: "kkkk", "kkkkkkk", "hahaha", "rsrs".
# Listar as variações uma a uma não funciona — na conferência sobre o corpus real
# "kkkkk" (cinco kk) passou por estar fora da lista, e virou palavra-chave de dois
# temas. Regra em vez de lista.
RISO = re.compile(r"^(?:k{2,}|(?:ha){2,}|(?:rs){2,}|h[aeiu]{2,}|s{2,})$", re.IGNORECASE)


def _sem_acento(palavra: str) -> str:
    """Forma sem acento, só para COMPARAR com a lista de stopwords.

    O texto que vai para o TF-IDF mantém o acento. Isto existe porque comentário
    de YouTube escreve "nao", "ja", "voce" sem acento o tempo todo, e uma lista
    de stopwords acentuada deixaria passar metade das ocorrências.
    """
    decomposta = unicodedata.normalize("NFD", palavra)
    return "".join(c for c in decomposta if unicodedata.category(c) != "Mn")


# Stopwords do português. Lista própria, e não NLTK ou spaCy, porque o backend
# de produção não carrega pacote de NLP para isso — a lista é dado, não código,
# e cabe aqui (CLAUDE.md Seção 10: nada de dependência que não paga o próprio
# peso). Escrita SEM acento: a comparação normaliza os dois lados.
_STOPWORDS_BASE = """
a agora ai ainda algo alguem alguma algumas alguns ali ampla amplas amplo amplos
ante antes ao aos apos aquela aquelas aquele aqueles aquilo as ate atraves
cada coisa coisas com como contra contudo da daquele daqueles das de dela delas
dele deles depois dessa dessas desse desses desta destas deste destes deve devem
devendo dever devera deverao deveria deveriam devia deviam disse disso disto dito
diz dizem do dos e ela elas ele eles em enquanto entao entre era essa essas esse
esses esta estamos estao estas estava estavam estavamos este esteja estejam
estes esteve estive estivemos estiveram estou eu fazendo fazer feita feitas feito
feitos foi for foram forem formos fosse fossem fui ha isso isto ja la lhe lhes lo
logo mas me mesma mesmas mesmo mesmos meu meus minha minhas muita muitas muito
muitos na nao nas nem nenhum nessa nessas nesta nestas ninguem no nos nossa
nossas nosso nossos num numa nunca o os ou outra outras outro outros para pela
pelas pelo pelos pequena pequenas pequeno pequenos per perante pode podendo poder
poderia poderiam podia podiam pois por porem porque posso pouca poucas pouco
poucos primeiro primeiros propria proprias proprio proprios quais qual qualquer
quando quanto quanta quantas quantos que quem quer querem quem sao se seja sejam
sem sempre sendo sera serao seria seriam seu seus si sido so sob sobre sua suas
talvez tambem tampouco te tem tendo tenha tenham tenho ter teu teus ti tido tinha
tinham tive tivemos tiveram toda todas todo todos tu tua tuas tudo um uma umas
uns vai vao vendo ver vez vindo vir voce voces vos
mais menos aqui ali la aonde onde assim entao ainda so apenas mesmo ja
vou vem veio vamos fica ficou ficar faz fez fazia dar da deu ter tem
coisa jeito modo forma parte lado hora dia dias ano anos vezes
"""

# Ruído específico de comentário de YouTube: interjeição, riso e vocativo. Não
# são stopwords do idioma — são stopwords DESTE corpus, e o motivo de estarem
# aqui é que sem elas o tema mais forte de qualquer execução é "kkkk, gente, cara".
_STOPWORDS_CORPUS = """
kkkk kkk kk haha hahaha rsrs ne ta to pra pro vc vcs q tb tbm eh aq blz
gente cara mano gata galera pessoal video videos comercial propaganda anuncio
youtube canal inscrito inscritos like curtida curtidas comentario comentarios
oi ola opa nossa caramba nao_sei
"""


def _montar_stopwords() -> frozenset[str]:
    """A lista final: idioma + ruído do corpus + as palavras que o emoji cria.

    As do emoji vêm de `MAPA_EMOJI` por importação, e não copiadas: um emoji
    novo no mapa entra aqui sozinho. Sem isso, a lista silenciosamente deixaria
    de cobrir o mapa na primeira vez que alguém o estendesse.
    """
    palavras = set(_STOPWORDS_BASE.split()) | set(_STOPWORDS_CORPUS.split())

    for valor in MAPA_EMOJI.values():
        # Um valor do mapa pode ser expressão de duas palavras ("por favor").
        for parte in valor.split():
            limpa = _sem_acento(parte.strip().lower())
            if limpa:
                palavras.add(limpa)

    return frozenset(palavras)


STOPWORDS = _montar_stopwords()

# As palavras que o mapa de emoji produz, isoladas — o teste usa para provar que
# nenhuma delas consegue virar tema.
PALAVRAS_DE_EMOJI = frozenset(
    _sem_acento(parte.strip().lower())
    for valor in MAPA_EMOJI.values()
    for parte in valor.split()
    if parte.strip()
)


def _e_emoji_ou_simbolo(caractere: str) -> bool:
    """Emoji, pictograma e modificador — tudo que não é letra, dígito ou pontuação.

    Vai por categoria Unicode em vez de lista de intervalos: a lista envelhece a
    cada versão do Unicode, a categoria não.
    """
    return unicodedata.category(caractere) in {"So", "Sk", "Cf"}


def limpar(texto: str) -> str:
    """O texto original pronto para o TF-IDF: minúsculo, sem link, menção nem emoji.

    A pontuação sobra de propósito: quem a descarta é a tokenização por
    `PALAVRA`, e tirá-la aqui duplicaria a regra em dois lugares.

    >>> limpar("Olha isso https://x.com @canal 😍 que CARRO bonito!")
    'olha isso       que carro bonito!'
    """
    sem_ruido = URL.sub(" ", texto)
    sem_ruido = MENCAO.sub(" ", sem_ruido)
    sem_ruido = TIMESTAMP.sub(" ", sem_ruido)
    sem_ruido = "".join(" " if _e_emoji_ou_simbolo(c) else c for c in sem_ruido)
    return sem_ruido.lower().strip()


def tokenizar(texto: str) -> list[str]:
    """Palavras úteis do texto já limpo, DOBRADAS para a forma sem acento.

    **Por que sem acento aqui, se o classificador léxico exige o acento.** São
    tarefas diferentes e a medição mostrou isso. O léxico casa palavra contra um
    dicionário, onde "mas" e "más" são entradas distintas e confundi-las injeta
    -1 em toda frase adversativa (`ml/lexico/README.md`, decisão 4). Aqui não há
    dicionário: o que se conta é co-ocorrência, e manter o acento PARTE a mesma
    palavra em duas features. Na conferência sobre o corpus real isso produziu
    dois temas gêmeos — "música / vim / nome" e "boa / musica / nome" —, que são
    o mesmo assunto ("qual é a música do anúncio?") separado por acento.

    O risco do léxico não existe aqui porque "mas" e "más" são as duas stopwords.

    O rótulo do tema mostra a grafia acentuada mais frequente do corpus; quem
    faz esse mapeamento é `modelo.modelar`, que vê as duas formas.

    >>> tokenizar("o carro é muito bonito e o preço não é caro")
    ['carro', 'bonito', 'preco', 'caro']
    """
    tokens = []
    for bruto in PALAVRA.findall(texto):
        if len(bruto) < MIN_CARACTERES_TOKEN:
            continue
        if RISO.match(bruto):
            continue
        dobrado = _sem_acento(bruto)
        if dobrado in STOPWORDS:
            continue
        tokens.append(dobrado)
    return tokens


def preparar(texto: str) -> list[str]:
    """`limpar` + `tokenizar`, que é como o vetorizador consome um comentário."""
    return tokenizar(limpar(texto))
