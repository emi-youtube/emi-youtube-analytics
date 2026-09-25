"""Modelagem de tópicos: TF-IDF + NMF. Funções puras, sem banco.

**Por que TF-IDF + NMF, e não embeddings do modelo de sentimento.** Duas razões,
e as duas são decisões registradas:

1. **Memória.** O worker roda no mesmo processo do runner, num contêiner da
   camada gratuita do Azure. Um segundo modelo neural residente ao lado do
   classificador não cabe — e a fila é uma tabela justamente para não pagar
   infraestrutura (CLAUDE.md Seção 10).
2. **Validade.** Reaproveitar a representação do classificador de SENTIMENTO
   para agrupar ASSUNTO é circular: aquele espaço foi treinado para separar
   positivo de negativo, então os agrupamentos tenderiam a reproduzir o
   sentimento e a PME veria "elogios" e "críticas" como se fossem temas. O TF-IDF
   não sabe o que é sentimento; ele só sabe que palavra aparece com que
   frequência, que é o que "assunto" quer dizer aqui.

NMF e não LDA: NMF sobre TF-IDF é determinístico dada a semente, converge em
segundos nesta escala e produz componentes esparsos — que é o que faz um tema
ser descritível por dez palavras. LDA continua citado como alternativa no TC2
(Seção 2), e trocar um pelo outro não muda nada fora deste arquivo.
"""

import logging
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

from app.insights.configuracao import PADRAO
from app.topicos.texto import PALAVRA, PALAVROES, limpar, preparar

logger = logging.getLogger(__name__)

# Semente fixa: rodar duas vezes sobre o mesmo corpus tem de dar os mesmos temas.
# Sem isto o painel mudaria de tema a cada reprocessamento e a banca não
# reproduziria a figura do relatório.
SEMENTE = 42

# --- quantos temas ---------------------------------------------------------
#
# Os dois cortes abaixo NÃO são números escolhidos no gosto: saem da
# configuração do motor de insights, para não divergirem dela.

MINIMO_DE_COMENTARIOS = PADRAO.minimo_execucao
"""Abaixo disto a execução não recebe tema NENHUM, e o motivo é registrado.

É o mesmo corte que o motor de insights usa para não afirmar nada sobre uma
execução (`minimo_execucao`, hoje 100). Gerar tema abaixo dele produziria temas
que nenhum insight pode citar e que a tela mostraria como se fossem achados —
uma execução de 40 comentários não tem tema, tem 40 comentários."""

COMENTARIOS_POR_TEMA = PADRAO.minimo_tema
"""Nunca criar mais temas do que caberia com `minimo_tema` comentários cada.

Um tema com menos de 30 comentários não pode ser apontado como mais criticado
nem como melhor recebido (`minimo_tema`), então criá-lo é criar uma linha que a
análise nunca vai conseguir usar."""

MINIMO_DE_TEMAS = 3
"""Menos de três grupos não é agrupamento: é a execução partida ao meio."""

MAXIMO_DE_TEMAS = 8
"""Teto do painel. A tela é um resumo para uma PME, não uma taxonomia; acima de
oito linhas o usuário deixa de ler a lista e passa a varrer."""

# --- pesos -----------------------------------------------------------------

LIMIAR_DE_PESO = 0.25
"""Participação mínima do tema no comentário para a ligação ser gravada.

O peso é a fração da "massa" do comentário que o tema explica, então 0,25 quer
dizer "este tema responde por pelo menos um quarto do que este comentário diz".
Sem um limiar, cada comentário entraria em TODOS os temas com peso minúsculo e
`COMENTARIO_TEMA` viraria o produto cartesiano — a tela mostraria todo
comentário em todo tema, que é o mesmo que não agrupar."""

MINIMO_TOKENS_NO_VOCABULARIO = 2
"""Palavras do vocabulário que o comentário precisa ter para entrar em algum tema.

O peso é normalizado pela massa do PRÓPRIO comentário, então um comentário com
uma única palavra conhecida recebe peso 1,0 no tema dessa palavra — confiança
máxima sustentada por uma evidência só. Na conferência sobre o corpus real isso
elegeu "Vamos todos cantar juntos, Lowlands Lowlands Away" como representante do
tema "claro / net / internet": o comentário não fala de operadora nenhuma, só
tinha pouquíssimo vocabulário e a normalização transformou ruído em certeza.

O valor saiu de medição sobre os 2.789 comentários da execução 4, não de gosto.
Contando quantos temas tiveram um representante que de fato contém uma das três
palavras do próprio rótulo:

    mínimo | cobertura        | representantes coerentes
    -------|------------------|-------------------------
      1    | 2.364/2.789 85%  | 7 de 8
      2    | 1.862/2.789 67%  | 8 de 8
      3    | 1.401/2.789 50%  | 8 de 8
      4    |   997/2.789 36%  | 7 de 8

Dois é onde a coerência satura: subir para três custa 17 pontos de cobertura e
não compra qualidade nenhuma. Duas palavras não tornam a atribuição correta, mas
tiram do jogo o caso em que ela é aritmeticamente inevitável.

Um terço dos comentários ficar sem tema é resultado, não falha: comentário de
YouTube é curto, e o `ml/lexico/README.md` já registra o mesmo fenômeno do outro
lado (44% sem nenhuma palavra do SentiLex). Forçar cada comentário no tema mais
próximo encheria a tela de atribuições que ninguém consegue defender."""

MINIMO_CARACTERES_REPRESENTATIVO = 40
"""Comprimento mínimo para um comentário poder representar um tema.

O de maior peso costuma ser o mais curto: um comentário de três palavras, todas
do tema, tem massa concentrada. Só que "preço alto" não mostra à PME o que as
pessoas estão dizendo sobre preço. Abaixo deste corte o comentário conta para o
tema, mas não fala por ele."""

# --- vetorização -----------------------------------------------------------

MIN_DF = 3
"""Palavra precisa aparecer em ao menos 3 comentários para entrar no vocabulário.
Corta erro de digitação e o nome próprio que uma pessoa só usou."""

MAX_DF = 0.4
"""E em no máximo 40% deles. Palavra presente em quase todo comentário não
separa nada — é stopword específica daquele corpus (o nome da marca, por
exemplo) e entraria em todos os temas de uma vez."""


@dataclass(frozen=True, slots=True)
class TemaEncontrado:
    """Um tema, pronto para virar linha de TEMAS."""

    indice: int
    rotulo: str
    palavras_chave: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Atribuicao:
    """Uma ligação comentário-tema, pronta para virar linha de COMENTARIO_TEMA."""

    id_comentario: int
    indice_tema: int
    peso: float


@dataclass(frozen=True, slots=True)
class ResultadoTopicos:
    """O que a modelagem produziu — ou por que não produziu nada.

    `motivo` preenchido e `temas` vazio é resultado VÁLIDO, não falha: execução
    pequena demais, ou vocabulário pobre demais, não tem tema. O worker registra
    o motivo e conclui a execução normalmente.
    """

    temas: tuple[TemaEncontrado, ...] = ()
    atribuicoes: tuple[Atribuicao, ...] = ()
    motivo: str | None = None

    @property
    def houve_temas(self) -> bool:
        return bool(self.temas)


def numero_de_temas(quantidade_de_comentarios: int) -> int:
    """Quantos temas extrair de uma execução deste tamanho.

    A regra, e o que cada termo impede:

        k = clamp(min(n // 30, round(sqrt(n) / 4)), 3, 8)

    - `n // COMENTARIOS_POR_TEMA` impede criar tema que a análise não pode usar
      (menos de 30 comentários cada, em média);
    - `sqrt(n) / 4` faz o número crescer com o corpus, mas devagar: dobrar os
      comentários não dobra os assuntos de uma campanha;
    - o `clamp` põe o piso do que é agrupamento e o teto do que cabe na tela.

    >>> [numero_de_temas(n) for n in (100, 300, 500, 1000, 2789, 5000)]
    [3, 4, 6, 8, 8, 8]
    """
    n = quantidade_de_comentarios
    por_amostra = n // COMENTARIOS_POR_TEMA
    por_crescimento = round(n**0.5 / 4)
    return max(MINIMO_DE_TEMAS, min(MAXIMO_DE_TEMAS, min(por_amostra, por_crescimento)))


def _sem_acento(palavra: str) -> str:
    """Forma sem acento — os palavrões são guardados assim, como as stopwords."""
    decomposta = unicodedata.normalize("NFD", palavra)
    return "".join(c for c in decomposta if unicodedata.category(c) != "Mn")


def _grafias_do_corpus(textos: list[str]) -> dict[str, str]:
    """Para cada forma sem acento, a grafia acentuada mais frequente do corpus.

    O vetorizador trabalha com a forma dobrada ("musica"), que é o que junta as
    duas grafias num único assunto. Mas o rótulo que a PME lê tem de estar
    escrito como gente escreve — "música". Quem decide é o próprio corpus: vence
    a grafia que mais apareceu, com desempate alfabético para a escolha não
    depender da ordem de leitura.
    """
    contagem: dict[str, Counter] = defaultdict(Counter)
    for texto in textos:
        for bruto in PALAVRA.findall(limpar(texto)):
            decomposta = unicodedata.normalize("NFD", bruto)
            dobrada = "".join(c for c in decomposta if unicodedata.category(c) != "Mn")
            contagem[dobrada][bruto] += 1

    return {
        dobrada: sorted(grafias.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        for dobrada, grafias in contagem.items()
    }


def _rotular(palavras: tuple[str, ...]) -> str:
    """Rótulo do tema: as três palavras mais fortes que não sejam palavrão.

    Nada de rótulo "bonito" inventado por LLM: o rótulo é o que o método achou,
    e a banca precisa poder conferir a origem dele na lista de palavras-chave.

    **O palavrão é pulado aqui e SÓ aqui.** Ele continua no vocabulário e nas
    `palavras_chave`, porque é sinal legítimo de reclamação e apagá-lo maquiaria
    o resultado. O que muda é que o rótulo — o nome curto que a PME leva para um
    relatório ou uma reunião — pega a próxima palavra forte no lugar. Na
    conferência sobre o corpus real o tema da operadora vinha com "merda" e
    "bosta" entre as dez mais fortes; com este filtro ele se chama
    "claro / net / internet" e não perde nenhuma informação.

    Se as dez palavras forem todas palavrão (não aconteceu no corpus real, mas é
    possível num tema de puro xingamento), o rótulo usa as três primeiras mesmo
    assim: um tema sem nome nenhum seria pior que um tema com nome feio.
    """
    limpas = tuple(p for p in palavras if _sem_acento(p.lower()) not in PALAVROES)
    escolhidas = limpas if len(limpas) >= 3 else palavras
    return " / ".join(escolhidas[:3])


def modelar(
    comentarios: list[tuple[int, str]],
    *,
    semente: int = SEMENTE,
) -> ResultadoTopicos:
    """Extrai os temas de `(id_comentario, texto_original)`.

    Não toca no banco e não decide nada sobre persistência: devolve os temas e as
    ligações, e quem grava é o worker.
    """
    total = len(comentarios)
    if total < MINIMO_DE_COMENTARIOS:
        return ResultadoTopicos(
            motivo=(
                f"execucao com {total} comentarios, abaixo do minimo de "
                f"{MINIMO_DE_COMENTARIOS} para modelagem de topicos"
            )
        )

    ids = [id_comentario for id_comentario, _ in comentarios]
    # `preparar` devolve a lista de tokens; o vetorizador recebe texto, então
    # junta de volta. O `analyzer` padrão não é usado: a limpeza (emoji, URL,
    # stopword) é nossa e precisa valer igual em todo lugar.
    documentos = [" ".join(preparar(texto)) for _, texto in comentarios]

    nao_vazios = sum(1 for doc in documentos if doc)
    if nao_vazios < MINIMO_DE_COMENTARIOS:
        return ResultadoTopicos(
            motivo=(
                f"apenas {nao_vazios} comentarios sobraram com texto util apos a limpeza "
                f"(emoji, link e stopword), abaixo do minimo de {MINIMO_DE_COMENTARIOS}"
            )
        )

    vetorizador = TfidfVectorizer(
        min_df=MIN_DF,
        max_df=MAX_DF,
        # A limpeza já aconteceu: aqui é só separar por espaço, senão o
        # tokenizador padrão do sklearn desfaria o corte de token curto.
        tokenizer=str.split,
        preprocessor=None,
        lowercase=False,
        token_pattern=None,
    )
    try:
        matriz = vetorizador.fit_transform(documentos)
    except ValueError as erro:
        # Acontece quando min_df/max_df zeram o vocabulário.
        return ResultadoTopicos(motivo=f"vocabulario vazio apos os cortes de frequencia: {erro}")

    vocabulario = vetorizador.get_feature_names_out()
    if len(vocabulario) < MINIMO_DE_TEMAS:
        return ResultadoTopicos(
            motivo=(
                f"vocabulario de {len(vocabulario)} palavras e pequeno demais para "
                f"{MINIMO_DE_TEMAS} temas"
            )
        )

    k = min(numero_de_temas(total), len(vocabulario))

    modelo = NMF(
        n_components=k,
        random_state=semente,
        init="nndsvda",
        max_iter=400,
    )
    pesos_documento = modelo.fit_transform(matriz)  # (documentos x temas)
    pesos_palavra = modelo.components_  # (temas x vocabulario)

    grafias = _grafias_do_corpus([texto for _, texto in comentarios])

    temas: list[TemaEncontrado] = []
    for indice in range(k):
        # As 10 mais fortes do componente, da maior para a menor.
        ordenadas = pesos_palavra[indice].argsort()[::-1][:10]
        palavras = tuple(grafias.get(str(vocabulario[p]), str(vocabulario[p])) for p in ordenadas)
        temas.append(
            TemaEncontrado(indice=indice, rotulo=_rotular(palavras), palavras_chave=palavras)
        )

    # Quantas palavras do vocabulário cada comentário tem, para descartar as
    # atribuições que a normalização tornaria artificialmente confiantes.
    tokens_por_documento = matriz.getnnz(axis=1)

    atribuicoes: list[Atribuicao] = []
    for linha, id_comentario in enumerate(ids):
        if tokens_por_documento[linha] < MINIMO_TOKENS_NO_VOCABULARIO:
            continue
        pesos = pesos_documento[linha]
        soma = float(pesos.sum())
        if soma <= 0:
            # Comentário sem nenhuma palavra do vocabulário: não pertence a tema
            # nenhum, e isso é informação — não é para forçá-lo no mais próximo.
            continue
        for indice in range(k):
            peso = float(pesos[indice]) / soma
            if peso >= LIMIAR_DE_PESO:
                atribuicoes.append(
                    Atribuicao(
                        id_comentario=id_comentario,
                        indice_tema=indice,
                        peso=round(peso, 6),
                    )
                )

    return ResultadoTopicos(temas=tuple(temas), atribuicoes=tuple(atribuicoes))


def representante_do_tema(
    indice_tema: int,
    atribuicoes: tuple[Atribuicao, ...],
    textos: dict[int, str],
) -> int | None:
    """O comentário que fala pelo tema: o de maior peso, evitando os curtos demais.

    O de maior peso puro costuma ser o mais curto — um comentário de três
    palavras, todas do tema, tem a massa concentrada nele. Só que "preço alto"
    não mostra à PME o que as pessoas dizem sobre preço. Então o corte de
    comprimento vem primeiro e o peso decide dentro do que sobrou; se nenhum
    comentário do tema alcança o comprimento, vale o de maior peso mesmo curto —
    é melhor mostrar o curto que não mostrar nada.

    Empate de peso resolve pelo menor `id_comentario`, para a escolha ser a mesma
    em toda execução do método.
    """
    do_tema = [a for a in atribuicoes if a.indice_tema == indice_tema]
    if not do_tema:
        return None

    def chave(a: Atribuicao) -> tuple[float, int]:
        return (-a.peso, a.id_comentario)

    longos = [
        a
        for a in do_tema
        if len(textos.get(a.id_comentario, "")) >= MINIMO_CARACTERES_REPRESENTATIVO
    ]
    escolhidos = longos or do_tema
    return sorted(escolhidos, key=chave)[0].id_comentario
