"""Sorteia a amostra humana (gabarito) e marca essas linhas como `split = 'teste'`.

Tamanho pela fórmula de Cochran com correção para população finita:

    n0 = Z² · p · (1-p) / e²          Z = 1,96 (95%), p = 0,5, e = 0,05
    n  = n0 / (1 + (n0 - 1) / N)

p = 0,5 é o caso de maior variância — a escolha conservadora quando não se conhece
a proporção real de antemão.

**O rótulo fraco serve só para sortear.** Estratificar por ele garante que as três
classes apareçam na amostra em volume parecido; se o sorteio fosse simples, a classe
minoritária (negativo, 27,2% do corpus da Sprint 1) apareceria pouco demais
para dizer qualquer coisa sobre ela. O avaliador humano NÃO vê esse rótulo — as
planilhas saem sem a coluna (`gerar_planilhas_avaliadores.py`).

Essas linhas viram `split = 'teste'`; o restante continua NULO até a partição
treino/validação ser atribuída. CLAUDE.md regra 6: o conjunto de teste é só humano.

**O sorteio só enxerga quem ainda está sem partição** (`split IS NULL`). É o que
torna possível a regra da Seção 9 do manual: se o Kappa ficar abaixo de 0,60, a
equipe reescreve o manual e sorteia uma amostra NOVA — e "nova" tem que significar
comentários que nenhum avaliador viu. Sortear de novo do corpus inteiro devolveria
parte dos mesmos comentários, e o segundo Kappa mediria memória do primeiro, não a
régua reescrita.

O `n` de Cochran continua calculado sobre o corpus rotulado inteiro: a precisão
declarada (95%, e=5%) é sobre o corpus, que não mudou de tamanho porque uma rodada
anterior gastou parte dele.

Uso:
    python -m ml.amostra.sortear_amostra_humana --id-execucao 4
    python -m ml.amostra.sortear_amostra_humana --id-execucao 4 --nova-rodada
    python -m ml.amostra.sortear_amostra_humana --id-execucao 4 --refazer
"""

import argparse
import asyncio
import logging
import math
import random
import sys
from collections import Counter, defaultdict

import asyncpg

from ml.config import CLASSES, SEMENTE, dsn_postgres

logger = logging.getLogger("amostra_humana")

# Parâmetros de Cochran, fixados no documento acadêmico.
Z_95 = 1.96
PROPORCAO = 0.5
ERRO = 0.05

SPLIT_TESTE = "teste"


def tamanho_cochran(populacao: int, z: float = Z_95, p: float = PROPORCAO, e: float = ERRO) -> int:
    """Tamanho de amostra de Cochran com correção para população finita.

    >>> tamanho_cochran(2534)
    334
    """
    n0 = (z**2) * p * (1 - p) / (e**2)
    n = n0 / (1 + (n0 - 1) / populacao)
    return math.ceil(n)


def alocar_por_estrato(tamanho: int, disponivel: dict[str, int]) -> dict[str, int]:
    """Divide a amostra em ~1/3 por classe, sem pedir mais do que existe.

    Quando um estrato tem menos exemplos que a cota, leva todos e a sobra é
    redistribuída entre os que ainda têm folga — senão a amostra sairia menor que o
    n de Cochran e o erro amostral deixaria de ser os 5% declarados.
    """
    estratos = [classe for classe in CLASSES if disponivel.get(classe, 0) > 0]
    if not estratos:
        return {}

    alocado = dict.fromkeys(estratos, 0)
    restante = tamanho

    # Distribui em rodadas: cada rodada dá 1 a cada estrato com folga. Converge para
    # ~1/3 por classe e absorve naturalmente o estrato pequeno.
    while restante > 0:
        com_folga = [c for c in estratos if alocado[c] < disponivel[c]]
        if not com_folga:
            break
        for classe in com_folga:
            if restante == 0:
                break
            alocado[classe] += 1
            restante -= 1

    if restante:
        logger.warning(
            "faltaram %s exemplo(s) para completar o n de Cochran: o corpus rotulado "
            "tem so %s exemplos",
            restante,
            sum(disponivel.values()),
        )
    return alocado


async def contar_rotulados(conexao: asyncpg.Connection, id_execucao: int) -> int:
    """População do `n` de Cochran: o corpus rotulado inteiro, com partição ou sem.

    Não é o mesmo que o pool sorteável. Uma rodada anterior pode já ter consumido
    parte do corpus, mas a precisão declarada (95%, e=5%) é sobre o corpus — que não
    encolheu porque alguém já foi avaliado.
    """
    return await conexao.fetchval(
        """
        SELECT count(*)
        FROM exemplos_treinamento e
        JOIN comentarios c ON c.id_comentario = e.id_comentario
        JOIN videos v ON v.id_video = c.id_video
        WHERE v.id_execucao = $1 AND e.rotulo_fraco IS NOT NULL
        """,
        id_execucao,
    )


async def carregar_sorteaveis(
    conexao: asyncpg.Connection, id_execucao: int
) -> list[asyncpg.Record]:
    """Quem pode ser sorteado: rotulado pela Gemini e **ainda sem partição**.

    O `split IS NULL` é a regra da Seção 9 do manual em SQL. Sem ele, uma segunda
    rodada (Kappa < 0,60) devolveria comentários que os avaliadores já tinham visto,
    e o novo Kappa mediria a memória deles, não o manual reescrito.
    """
    return await conexao.fetch(
        """
        SELECT e.id_exemplo, e.id_comentario, e.rotulo_fraco, e.split
        FROM exemplos_treinamento e
        JOIN comentarios c ON c.id_comentario = e.id_comentario
        JOIN videos v ON v.id_video = c.id_video
        WHERE v.id_execucao = $1 AND e.rotulo_fraco IS NOT NULL AND e.split IS NULL
        ORDER BY e.id_comentario
        """,
        id_execucao,
    )


async def sortear(id_execucao: int, refazer: bool, nova_rodada: bool = False) -> dict[str, int]:
    """Sorteia a amostra humana.

    `refazer` descarta a amostra anterior (ela volta para NULL e pode ser sorteada de
    novo) — serve para o erro de operação, antes de qualquer avaliador abrir planilha.

    `nova_rodada` é o caso da Seção 9 do manual: o Kappa ficou abaixo de 0,60, o
    manual foi reescrito e a equipe precisa de uma amostra NOVA. A anterior continua
    marcada — ninguém rotula duas vezes o mesmo comentário — e o sorteio sai só de
    quem ainda está sem partição.
    """
    sorteio = random.Random(SEMENTE)

    if refazer and nova_rodada:
        raise SystemExit(
            "--refazer e --nova-rodada sao opostos: um descarta a amostra anterior, o "
            "outro a preserva justamente para nao reapresenta-la a ninguem. Escolha um."
        )

    conexao = await asyncpg.connect(dsn_postgres())
    try:
        ja_teste = await conexao.fetchval(
            """
            SELECT count(*) FROM exemplos_treinamento e
            JOIN comentarios c ON c.id_comentario = e.id_comentario
            JOIN videos v ON v.id_video = c.id_video
            WHERE v.id_execucao = $1 AND e.split = $2
            """,
            id_execucao,
            SPLIT_TESTE,
        )
        if ja_teste and not (refazer or nova_rodada):
            raise SystemExit(
                f"{ja_teste} exemplo(s) ja estao com split='teste'. Use --nova-rodada para "
                "sortear outra amostra entre os que ainda nao tem particao (Kappa < 0,60, "
                "manual reescrito), ou --refazer para descartar a anterior."
            )
        if ja_teste and refazer:
            # Volta para NULL antes de sortear: manter o teste antigo somado ao novo
            # inflaria o conjunto e quebraria o n de Cochran.
            await conexao.execute(
                """
                UPDATE exemplos_treinamento e SET split = NULL
                FROM comentarios c, videos v
                WHERE c.id_comentario = e.id_comentario AND v.id_video = c.id_video
                  AND v.id_execucao = $1 AND e.split = $2
                """,
                id_execucao,
                SPLIT_TESTE,
            )
            logger.warning("amostra anterior desfeita (%s linhas voltaram para NULL)", ja_teste)
        if ja_teste and nova_rodada:
            logger.warning(
                "amostra anterior PRESERVADA (%s linhas seguem com split='teste'); "
                "a nova sai so de quem esta sem particao",
                ja_teste,
            )

        registros = await carregar_sorteaveis(conexao, id_execucao)
        if not registros:
            raise SystemExit(
                "Nenhum exemplo rotulado e sem particao para sortear. Rode antes: "
                "python -m ml.rotulagem.rotular_fraco --id-execucao <N>"
            )

        # N de Cochran: o corpus rotulado inteiro. O pool sorteavel pode ser menor
        # (uma rodada anterior consumiu parte dele), mas a precisao declarada e sobre
        # o corpus, nao sobre o que sobrou.
        populacao = await contar_rotulados(conexao, id_execucao)
        tamanho = tamanho_cochran(populacao)

        por_classe: dict[str, list[int]] = defaultdict(list)
        for registro in registros:
            por_classe[registro["rotulo_fraco"]].append(registro["id_comentario"])

        disponivel = {classe: len(ids) for classe, ids in por_classe.items()}
        cotas = alocar_por_estrato(tamanho, disponivel)

        escolhidos: list[int] = []
        for classe in CLASSES:
            ids = sorted(por_classe.get(classe, []))
            cota = cotas.get(classe, 0)
            if not cota:
                continue
            escolhidos.extend(sorteio.sample(ids, cota))
        escolhidos.sort()

        await conexao.executemany(
            "UPDATE exemplos_treinamento SET split = $2 WHERE id_comentario = $1",
            [(id_comentario, SPLIT_TESTE) for id_comentario in escolhidos],
        )

        logger.info("=" * 62)
        logger.info("AMOSTRA HUMANA (gabarito)")
        logger.info("=" * 62)
        logger.info("  populacao rotulada (N) ..... %5d", populacao)
        logger.info("  sorteaveis (sem particao) .. %5d", len(registros))
        logger.info("  n de Cochran (95%%, e=5%%) ... %5d", tamanho)
        logger.info("  semente .................... %5d", SEMENTE)
        logger.info("-" * 62)
        logger.info("  %-10s %10s %10s", "classe", "disponivel", "sorteado")
        for classe in CLASSES:
            logger.info(
                "  %-10s %10d %10d", classe, disponivel.get(classe, 0), cotas.get(classe, 0)
            )
        logger.info("-" * 62)
        logger.info("  marcados como split='teste': %5d", len(escolhidos))
        logger.info("=" * 62)

        conferencia = Counter(
            r["rotulo_fraco"] for r in registros if r["id_comentario"] in set(escolhidos)
        )
        logger.info("conferencia da distribuicao sorteada: %s", dict(conferencia))
        return cotas
    finally:
        await conexao.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument(
        "--refazer", action="store_true", help="descarta a amostra anterior e sorteia de novo"
    )
    parser.add_argument(
        "--nova-rodada",
        action="store_true",
        help="Kappa < 0,60: preserva a amostra anterior e sorteia outra entre os sem particao",
    )
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)
    asyncio.run(sortear(argumentos.id_execucao, argumentos.refazer, argumentos.nova_rodada))


if __name__ == "__main__":
    main()
