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


# ---------------------------------------------------------------------------
# Stopwords
# ---------------------------------------------------------------------------
#
# ORIGEM DA LISTA (citar no TC2):
#
#   Bird, S.; Klein, E.; Loper, E. *Natural Language Processing with Python*.
#   O'Reilly, 2009. Corpus `stopwords`, idioma `portuguese`, do NLTK
#   (Natural Language Toolkit), versao 3.10.3 — 207 termos.
#   Obtida com: nltk.corpus.stopwords.words("portuguese")
#
# **A lista e EMBUTIDA, e o NLTK nao e dependencia de runtime.** O corpus
# `stopwords` nao vem no pacote: exige `nltk.download("stopwords")`, que precisa
# de rede e de diretorio gravavel no primeiro uso. Um worker que baixa corpus ao
# subir falha no contêiner por motivo que nada tem a ver com a analise, e o
# CLAUDE.md Secao 10 e explicito sobre nao pagar peso que nao se usa. A lista e
# DADO, tem 207 termos e nao muda ha anos; embuti-la com a citacao acima da o
# mesmo resultado, reproduzivel e sem rede.
#
# Guardada SEM ACENTO porque e assim que a comparacao acontece: o tokenizador
# dobra o acento antes de comparar (ver `tokenizar`).
_STOPWORDS_NLTK = """
a ao aos aquela aquelas aquele aqueles aquilo as ate com como da das de dela
delas dele deles depois do dos e ela elas ele eles em entre era eram eramos
essa essas esse esses esta estamos estao estar estas estava estavam
estavamos este esteja estejam estejamos estes esteve estive estivemos
estiver estivera estiveram estiveramos estiverem estivermos estivesse
estivessem estivessemos estou eu foi fomos for fora foram foramos forem
formos fosse fossem fossemos fui ha haja hajam hajamos hao havemos haver hei
houve houvemos houver houvera houveram houveramos houverao houverei houverem
houveremos houveria houveriam houveriamos houvermos houvesse houvessem
houvessemos isso isto ja lhe lhes mais mas me mesmo meu meus minha minhas
muito na nao nas nem no nos nossa nossas nosso nossos num numa o os ou para
pela pelas pelo pelos por qual quando que quem sao se seja sejam sejamos sem
ser sera serao serei seremos seria seriam seriamos seu seus so somos sou sua
suas tambem te tem temos tenha tenham tenhamos tenho tera terao terei
teremos teria teriam teriamos teu teus teve tinha tinham tinhamos tive
tivemos tiver tivera tiveram tiveramos tiverem tivermos tivesse tivessem
tivessemos tu tua tuas um uma voce voces vos
"""

# Acrescimos do PROJETO, que a lista de idioma nao cobre porque nao sao do
# idioma: sao deste corpus. Cada grupo entrou por ter aparecido nos temas da
# conferencia sobre a execucao 4 — o registro de qual defeito cada um corrige
# esta no historico do repositorio.
_STOPWORDS_PROJETO = """
# abreviacao e giria de comentario
vc vcs voces tbm tb pq pra pro porq ne ta to eh aq blz mto mt dnv tlg msm
vdd sla pfv pfvr obg vlw flw hj agr qnd qm oq
# cumprimento e cortesia (o tema 'boa / noite / internet' era isto)
oi ola opa bom boa dia noite tarde manha obrigado obrigada valeu parabens
desculpa licenca
# vocativo e interjeicao
gente cara mano gata galera pessoal nossa caramba deus meu uau eita aff putz
eba ihh
# verbo vazio (vim, ser e mto sairam nomeados na revisao)
vim ser sendo estar ficar ficou fica parece parecer acho achei achou sei
sabia vejo visto faz fez fazia dar deu vou vai vamos quero queria espero
esperava tem tinha teve poder pode podia
# conectivo, adverbio e substantivo generico que a lista da NLTK nao cobre e
# que nao descrevem assunto nenhum. "melhor" e "pior" entram aqui de proposito:
# sao AVALIACAO, nao assunto, e como rotulo de tema ("melhor / publicidade /
# operadora") nao dizem a PME sobre o que o publico falou.
assim aqui ali la onde aonde entao apenas menos agora hoje ontem amanha sempre
nunca talvez alias enfim tipo coisa coisas jeito forma modo lado parte hora
vez vezes ano anos dias melhor pior maior menor novo nova velho outro toda
todo cada algum nenhum bem mal desde apos antes durante
# demonstrativo, intensificador e verbo de suporte que a NLTK nao lista e que
# sobraram nos rotulos da conferencia por campanha ("nome / saber / dessa",
# "renault / boreal / tudo"). "top", "show" e "demais" entram como GIRIA
# AVALIATIVA: dizem que o publico gostou, que e o que a outra metade do sistema
# ja mede, e nao dizem de que ele estava falando.
ter ver ainda tudo desse dessa deste desta nesse nessa neste nesta disso nisso
tao sim alguem ninguem veio vir pegar top show demais legal massa foda-se
# meta do YouTube, que fala do veiculo e nao do assunto
video videos comercial propaganda anuncio anuncios youtube canal inscrito
inscritos like likes curtida curtidas comentario comentarios live shorts
"""


def _montar_stopwords() -> frozenset[str]:
    """A lista final: NLTK + acréscimos do projeto + as palavras que o emoji cria.

    As do emoji vêm de `MAPA_EMOJI` por importação, e não copiadas: um emoji
    novo no mapa entra aqui sozinho. Sem isso, a lista silenciosamente deixaria
    de cobrir o mapa na primeira vez que alguém o estendesse.
    """
    palavras = {
        termo
        for linha in (_STOPWORDS_NLTK + _STOPWORDS_PROJETO).splitlines()
        if not linha.lstrip().startswith("#")
        for termo in linha.split()
    }

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


# ---------------------------------------------------------------------------
# Palavrões
# ---------------------------------------------------------------------------
#
# Estas palavras NÃO são stopwords: elas ficam no vocabulário e continuam
# aparecendo nas `palavras_chave` do tema, porque são sinal legítimo — um tema
# de reclamação com "merda" e "porcaria" entre as palavras fortes está dizendo
# exatamente o que a PME precisa saber, e apagá-las maquiaria o resultado.
#
# O que elas não podem é entrar no RÓTULO. O rótulo é o nome curto que vai para
# a tela e para o relatório que a PME apresenta a um cliente ou a um diretor;
# um tema chamado "merda / net / internet" é impublicável ali, enquanto a mesma
# informação sobrevive na lista de palavras-chave logo ao lado.
#
# Lista curta e explícita de propósito: filtro de palavrão por heurística erra
# nos dois sentidos, e um falso positivo aqui apaga uma palavra legítima do
# rótulo em silêncio. Guardada sem acento, como as stopwords.
# "lixo" NAO entra: ele ja e stopword por vir do MAPA_EMOJI (a lixeira), entao
# nunca chega ao vocabulario e listá-lo aqui sugeriria, falsamente, que ele
# poderia aparecer nas palavras-chave.
_PALAVROES_BRUTO = """
merda bosta porcaria droga caca
puta putaria puto putos putas caralho carai caraio porra porras
foda fodas fodido fodida fuder foder fudeu
buceta cuzao babaca otario otarios otaria idiota idiotas imbecil
burro burra burros viado viados bicha corno cornos
desgraca desgracado inferno diabo
"""

PALAVROES = frozenset(_PALAVROES_BRUTO.split())
"""Palavras que ficam FORA do rótulo e DENTRO das palavras-chave.

Sem acento, como as stopwords: a comparação normaliza os dois lados.
"""


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
