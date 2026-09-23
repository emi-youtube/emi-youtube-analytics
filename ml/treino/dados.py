"""Os dados do fine-tuning: quem entra, com que texto e em que partição.

Sem `torch` e sem `transformers` de propósito — este módulo é sobre *quais* exemplos
o modelo vê, e essa pergunta precisa ser testável sem carregar meio giga de peso.

**Quem entra: os 2.200 de `split IS NULL`, com o `rotulo_fraco` da Gemini.** Os 334
da amostra humana (`split = 'teste'`) não entram em nenhuma etapa do treino — nem
como treino, nem como validação. É a regra 6 do CLAUDE.md na prática: o conjunto de
teste é só humano, e um exemplo que o modelo viu no treino não mede mais nada.

**A partição 85/15 é feita em MEMÓRIA e não volta para o banco.** Gravar `split` aqui
custaria caro na hora errada: se o Kappa ficar abaixo de 0,60, a Seção 9 do manual
manda sortear uma amostra humana NOVA, e o sorteio só enxerga quem está sem partição
(`ml/amostra/sortear_amostra_humana.py`). Marcar estes 2.200 como treino/validação
esvaziaria o pool do qual essa segunda rodada teria que sair. Enquanto o gabarito não
volta, a partição é um detalhe do ensaio, não um fato do corpus.

**O texto é o `texto_modelo`.** O banco guarda o original; `preparar_texto` é aplicado
aqui, na montagem do dataset, exatamente como o worker de inferência vai aplicar ao
comentário que chegar. Mesma função, mesmo código, mesma versão — é para isso que o
`preprocessamento/` existe como pacote separado (CLAUDE.md Seção 3).
"""

import logging
import random
from collections import Counter
from dataclasses import dataclass

import asyncpg
from preprocessamento import preparar_texto

from ml.config import CLASSES, SEMENTE, dsn_postgres

logger = logging.getLogger("treino")

# Fração que vai para validação. 15% de 2.200 são 330 exemplos — o suficiente para
# que uma diferença de 1 ponto de F1 macro entre dois hiperparâmetros não seja só
# ruído de arredondamento, e pequeno o bastante para sobrar treino.
FRACAO_VALIDACAO = 0.15

SPLIT_TESTE = "teste"


@dataclass(frozen=True)
class Exemplo:
    """Um exemplo de treino: o que o modelo lê, o que ele deve responder.

    `texto` é o canônico (o que a pessoa escreveu) e viaja junto só para conferência
    e para o relatório de erro — quem entra no modelo é `texto_modelo`.
    """

    id_comentario: int
    texto: str
    texto_modelo: str
    rotulo: str


@dataclass(frozen=True)
class Particao:
    """Treino e validação de uma rodada, já divididos."""

    treino: list[Exemplo]
    validacao: list[Exemplo]

    @property
    def total(self) -> int:
        return len(self.treino) + len(self.validacao)


async def carregar_exemplos(id_execucao: int) -> list[Exemplo]:
    """Lê os exemplos rotulados pela Gemini que ainda não têm partição.

    O `split IS NULL` é o que mantém os 334 da amostra humana fora do treino, sem
    precisar de uma lista de exclusão: quem foi sorteado para o gabarito já está
    marcado como `teste` desde `sortear_amostra_humana.py`.

    Comentário sem `rotulo_fraco` também fica de fora — não há o que aprender com
    exemplo sem rótulo, e a rotulagem fraca é justamente o passo anterior a este.
    """
    conexao = await asyncpg.connect(dsn_postgres())
    try:
        registros = await conexao.fetch(
            """
            SELECT e.id_comentario, e.texto, e.rotulo_fraco
            FROM exemplos_treinamento e
            JOIN comentarios c ON c.id_comentario = e.id_comentario
            JOIN videos v ON v.id_video = c.id_video
            WHERE v.id_execucao = $1
              AND e.split IS NULL
              AND e.rotulo_fraco IS NOT NULL
            ORDER BY e.id_comentario
            """,
            id_execucao,
        )
    finally:
        await conexao.close()

    exemplos = [
        Exemplo(
            id_comentario=registro["id_comentario"],
            texto=registro["texto"],
            texto_modelo=preparar_texto(registro["texto"]),
            rotulo=registro["rotulo_fraco"],
        )
        for registro in registros
    ]

    vazios = [exemplo.id_comentario for exemplo in exemplos if not exemplo.texto_modelo]
    if vazios:
        # Não deveria acontecer: a exportação já descarta texto vazio. Se acontecer,
        # é sintoma de mudança no pré-processamento, e treinar com string vazia
        # ensinaria o modelo a associar "nada" a um rótulo.
        raise ValueError(
            f"{len(vazios)} exemplo(s) ficaram sem texto apos preparar_texto "
            f"(ids: {vazios[:5]}). Reexporte o corpus antes de treinar."
        )

    fora_das_classes = {exemplo.rotulo for exemplo in exemplos} - set(CLASSES)
    if fora_das_classes:
        raise ValueError(f"rotulo_fraco fora das classes do projeto: {fora_das_classes}")

    return exemplos


async def carregar_teste(id_execucao: int) -> list[Exemplo]:
    """A amostra humana, para PREVER — nunca para treinar.

    Não traz `rotulo_humano` nem `rotulo_fraco`: quem chama isto produz previsões, e
    a comparação contra o gabarito é trabalho de `ml/avaliacao/`. Separar as duas
    coisas é o que faz "o teste é olhado uma única vez" ser uma propriedade do código
    e não uma promessa.
    """
    conexao = await asyncpg.connect(dsn_postgres())
    try:
        registros = await conexao.fetch(
            """
            SELECT e.id_comentario, e.texto
            FROM exemplos_treinamento e
            JOIN comentarios c ON c.id_comentario = e.id_comentario
            JOIN videos v ON v.id_video = c.id_video
            WHERE v.id_execucao = $1 AND e.split = $2
            ORDER BY e.id_comentario
            """,
            id_execucao,
            SPLIT_TESTE,
        )
    finally:
        await conexao.close()

    return [
        Exemplo(
            id_comentario=registro["id_comentario"],
            texto=registro["texto"],
            texto_modelo=preparar_texto(registro["texto"]),
            rotulo="",  # desconhecido aqui, e é para continuar assim
        )
        for registro in registros
    ]


def dividir_estratificado(
    exemplos: list[Exemplo],
    fracao_validacao: float = FRACAO_VALIDACAO,
    semente: int = SEMENTE,
) -> Particao:
    """Divide 85/15 mantendo a proporção das três classes nos dois lados.

    Estratificar importa porque o corpus é desbalanceado (44% positivo, 26% negativo):
    num sorteio simples, a validação poderia sair com poucos negativos, e o F1 macro
    — que pesa as três classes igualmente — passaria a depender de umas poucas
    dezenas de exemplos da classe minoritária.

    **Determinístico.** A entrada vem ordenada por `id_comentario` e o embaralhamento
    sai de `random.Random(semente)`, então a mesma execução produz a mesma partição em
    qualquer máquina. Sem isso, comparar dois hiperparâmetros mediria também a
    diferença entre duas validações.

    >>> exemplos = [Exemplo(i, "t", "t", "positivo") for i in range(10)]
    >>> particao = dividir_estratificado(exemplos, 0.2)
    >>> len(particao.treino), len(particao.validacao)
    (8, 2)
    """
    if not 0 < fracao_validacao < 1:
        raise ValueError(f"fracao_validacao deve ficar entre 0 e 1, veio {fracao_validacao}")

    sorteio = random.Random(semente)
    treino: list[Exemplo] = []
    validacao: list[Exemplo] = []

    por_classe: dict[str, list[Exemplo]] = {classe: [] for classe in CLASSES}
    for exemplo in exemplos:
        por_classe[exemplo.rotulo].append(exemplo)

    for classe in CLASSES:
        grupo = sorted(por_classe[classe], key=lambda exemplo: exemplo.id_comentario)
        sorteio.shuffle(grupo)
        quantidade = round(len(grupo) * fracao_validacao)
        validacao.extend(grupo[:quantidade])
        treino.extend(grupo[quantidade:])

    # Ordena os dois lados por id: o embaralhamento já cumpriu o papel dele (escolher
    # QUEM vai para cada lado), e a ordem de apresentação ao modelo é embaralhada a
    # cada época pelo próprio laço de treino.
    treino.sort(key=lambda exemplo: exemplo.id_comentario)
    validacao.sort(key=lambda exemplo: exemplo.id_comentario)
    return Particao(treino=treino, validacao=validacao)


def pesos_de_classe(exemplos: list[Exemplo], classes: tuple[str, ...] = CLASSES) -> list[float]:
    """`class_weight='balanced'` do scikit-learn, escrito à mão (CLAUDE.md regra 8).

        peso_j = N / (k * n_j)      N = total, k = numero de classes, n_j = da classe j

    Devolve na ordem de `classes` — a MESMA ordem do `id2label` do `model_card.json`.
    Trocar a ordem aqui daria à classe errada o peso da outra, e o efeito seria um
    modelo pior sem nenhuma mensagem de erro.

    **Calculado só sobre o treino.** Usar o corpus inteiro deixaria a composição da
    validação vazar para dentro da função de perda — vazamento pequeno, mas gratuito
    de evitar.

    Sem o peso, a saída ótima para a perda média é chutar `positivo` (44% do corpus):
    a acurácia sobe e o F1 macro desaba, que é exatamente o desfecho que a regra 8
    proíbe.

    >>> exemplos = [Exemplo(0, "t", "t", "positivo")] * 2 + [Exemplo(1, "t", "t", "neutro")]
    >>> pesos_de_classe(exemplos, ("positivo", "neutro"))
    [0.75, 1.5]
    """
    contagem = Counter(exemplo.rotulo for exemplo in exemplos)
    total = sum(contagem[classe] for classe in classes)
    if not total:
        raise ValueError("nenhum exemplo para calcular peso de classe")

    pesos: list[float] = []
    for classe in classes:
        if not contagem[classe]:
            raise ValueError(
                f"classe '{classe}' nao aparece no treino: o peso balanceado seria "
                "divisao por zero, e o modelo nunca aprenderia a preve-la"
            )
        pesos.append(total / (len(classes) * contagem[classe]))
    return pesos


def distribuicao(exemplos: list[Exemplo]) -> dict[str, int]:
    """Contagem por classe, na ordem do projeto — para relatório e metadados."""
    contagem = Counter(exemplo.rotulo for exemplo in exemplos)
    return {classe: contagem.get(classe, 0) for classe in CLASSES}


def relatar_particao(particao: Particao, pesos: list[float]) -> None:
    """Imprime o que entrou em cada lado. É o que se confere antes de gastar GPU."""
    logger.info("=" * 66)
    logger.info("DADOS DO ENSAIO - rotulo fraco (Gemini), split NULL")
    logger.info("=" * 66)
    logger.info("  treino ..... %5d", len(particao.treino))
    logger.info("  validacao .. %5d", len(particao.validacao))
    logger.info("  total ...... %5d", particao.total)
    logger.info("-" * 66)
    logger.info("  %-10s %10s %10s %10s", "classe", "treino", "validacao", "peso")
    contagem_treino = distribuicao(particao.treino)
    contagem_validacao = distribuicao(particao.validacao)
    for classe, peso in zip(CLASSES, pesos, strict=True):
        logger.info(
            "  %-10s %10d %10d %10.4f",
            classe,
            contagem_treino[classe],
            contagem_validacao[classe],
            peso,
        )
    logger.info("=" * 66)
