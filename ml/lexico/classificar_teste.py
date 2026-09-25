"""Classifica o conjunto de teste com o léxico e guarda as previsões em CSV.

A regra mora em `sentilex.py`; aqui fica o que toca banco e arquivo.

**Nada é gravado no banco.** A leitura é a única coisa que este script faz lá. As
previsões saem em `ml/dados/previsoes_lexico.csv`, e não em `ANALISES_SENTIMENTO`,
por dois motivos: aquela tabela tem `UNIQUE(id_comentario)` e é a superfície que o
dashboard lê — gravar a linha de base ali ocuparia o lugar da inferência de produção
para os mesmos comentários e faria o painel mostrar resultado de léxico. Além disso
exigiria criar uma linha em `VERSOES_MODELO`, que é escrita no banco além das
previsões. A comparação do Capítulo 5 é artefato de experimento, não análise de
produção.

**Entrada: `texto_modelo`.** O texto sai do banco canônico (original) e passa por
`preparar_texto` aqui, exatamente como o worker de inferência fará com o comentário
que chega ao BERTimbau. É o que isola o método na comparação (ver `README.md` desta
pasta).

Saída:
  `ml/dados/previsoes_lexico.csv`      previsões, uma por comentário (`.gitignore`)
  `ml/lexico/metadados_lexico.json`    só agregados e hashes — versionado

Uso:
    python -m ml.lexico.classificar_teste --id-execucao 4
    python -m ml.lexico.classificar_teste --id-execucao 4 --lexico caminho/lem.txt
"""

import argparse
import asyncio
import csv
import json
import logging
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
from preprocessamento import VERSAO as VERSAO_PREPROCESSAMENTO
from preprocessamento import preparar_texto

# A regra saiu de ml/lexico/ para o pacote compartilhado quando o worker de
# inferencia passou a precisar dela: e a MESMA soma de polaridade que produz o piso
# deste experimento e o rotulo que a PME ve no painel (CLAUDE.md Secao 3).
from lexico import VERSAO as VERSAO_LEXICO
from lexico import Lexico, Previsao, carregar, classificar
from ml.config import CLASSES, DIRETORIO_DADOS, DIRETORIO_ML, dsn_postgres

logger = logging.getLogger("lexico")

DIRETORIO_LEXICO = DIRETORIO_ML / "lexico"

# O arquivo `flex` (82.347 formas flexionadas) e não o `lem` (7.014 lemas): o
# pipeline não tem lematizador e não vai ganhar um só para a linha de base. Com o
# `lem`, "adorei" não casaria com "adorar" e o piso mediria a falta do lematizador
# em vez de medir o léxico.
ARQUIVO_LEXICO_PADRAO = DIRETORIO_LEXICO / "dados" / "SentiLex-flex-PT02.txt"

ARQUIVO_PREVISOES = DIRETORIO_DADOS / "previsoes_lexico.csv"
ARQUIVO_METADADOS = DIRETORIO_LEXICO / "metadados_lexico.json"

SPLIT_TESTE = "teste"

COLUNAS_CSV = ("id_comentario", "previsto", "escore", "positivos", "negativos", "termos")


async def carregar_teste(id_execucao: int) -> list[tuple[int, str]]:
    """Os comentários da amostra humana: `split='teste'`, texto CANÔNICO.

    Ordenado por `id_comentario` — a chave estável do corpus (`ml/README.md`). O
    `rotulo_humano` não é lido aqui de propósito: a previsão não pode depender do
    gabarito nem por acidente, e hoje ele ainda é NULO.
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
    return [(registro["id_comentario"], registro["texto"]) for registro in registros]


def gravar_previsoes(
    previsoes: list[tuple[int, Previsao]], caminho: Path, id_execucao: int
) -> None:
    """CSV de previsões: uma linha por comentário, na ordem de `id_comentario`.

    `termos` viaja junto porque é a única vantagem que o léxico tem sobre o
    BERTimbau: dá para abrir qualquer linha e ver que palavras produziram o rótulo.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # newline="" é exigência do csv no Windows: sem isso sai \r\r\n entre as linhas.
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(COLUNAS_CSV)
        for id_comentario, previsao in previsoes:
            escritor.writerow(
                [
                    id_comentario,
                    previsao.rotulo,
                    previsao.escore,
                    previsao.positivos,
                    previsao.negativos,
                    "|".join(f"{palavra}:{polaridade}" for palavra, polaridade in previsao.termos),
                ]
            )
    logger.info("previsoes -> %s (%s linhas)", caminho, len(previsoes))
    logger.info("id_execucao=%s", id_execucao)


def gravar_metadados(
    previsoes: list[tuple[int, Previsao]],
    lexico: Lexico,
    id_execucao: int,
    caminho: Path,
) -> None:
    """JSON de agregados — versionado, como o `metadados_rotulagem.json`.

    Só contagem, proporção e hash: nenhum texto de terceiros. É a evidência de que a
    linha de base do Capítulo 5 saiu deste recurso, desta versão do pré-processamento
    e desta regra — e o que permite reproduzi-la.
    """
    distribuicao = Counter(previsao.rotulo for _, previsao in previsoes)
    sem_cobertura = sum(1 for _, previsao in previsoes if not previsao.cobriu)
    total = len(previsoes)
    neutros = distribuicao.get("neutro", 0)

    conteudo = {
        "data_utc": datetime.now(UTC).isoformat(),
        "id_execucao": id_execucao,
        "metodo": "lexico (SentiLex-PT02, soma de polaridade)",
        # Versao do NOSSO classificador (a regra e o parser do recurso), nao do
        # SentiLex. E o mesmo numero que vai para VERSOES_MODELO.versao quando o
        # worker de inferencia grava com esta implementacao: o piso do capitulo e a
        # producao ficam rastreaveis a mesma versao de codigo.
        "versao_classificador": VERSAO_LEXICO,
        "recurso": {
            "nome": "SentiLex-PT02",
            "arquivo": lexico.arquivo,
            "sha256": lexico.sha256,
            "licenca": "CC-BY 4.0",
            "citacao": "Silva, Carvalho e Sarmento (2012), PROPOR",
            "entradas_lidas": lexico.entradas_lidas,
            "entradas_utilizaveis": len(lexico),
            "entradas_por_complemento": lexico.entradas_por_complemento,
            "descartes": lexico.descartes,
        },
        "regra": (
            "soma das polaridades das palavras conhecidas; sinal da soma decide. "
            "Sem negacao, intensificador ou desambiguacao: e o piso, nao um concorrente."
        ),
        "entrada": {
            "texto": "texto_modelo (preparar_texto)",
            "versao_preprocessamento": VERSAO_PREPROCESSAMENTO,
        },
        "total_comentarios": total,
        "distribuicao": {classe: distribuicao.get(classe, 0) for classe in CLASSES},
        "cobertura": {
            "sem_palavra_conhecida": sem_cobertura,
            "neutro_por_ausencia": sem_cobertura,
            "neutro_por_empate": neutros - sem_cobertura,
        },
    }
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("metadados -> %s", caminho)


def relatar(previsoes: list[tuple[int, Previsao]], lexico: Lexico) -> None:
    """Relatório de console. Sem métrica: o gabarito não entra aqui.

    Acurácia, F1 e matriz de confusão são trabalho de `ml/avaliacao/` — que compara
    QUALQUER conjunto de previsões contra o `rotulo_humano`. Misturar as duas coisas
    faria este script precisar do gabarito para rodar, e ele roda hoje, sem gabarito.
    """
    total = len(previsoes)
    distribuicao = Counter(previsao.rotulo for _, previsao in previsoes)
    sem_cobertura = sum(1 for _, previsao in previsoes if not previsao.cobriu)

    logger.info("")
    logger.info("=" * 66)
    logger.info("CLASSIFICADOR LEXICO - %s comentarios", total)
    logger.info("=" * 66)
    logger.info("  recurso ................. %s", lexico.arquivo)
    logger.info("  entradas lidas .......... %6d", lexico.entradas_lidas)
    logger.info("  entradas utilizaveis .... %6d", len(lexico))
    for motivo, quantidade in lexico.descartes.items():
        logger.info("    descartadas: %-20s %6d", motivo, quantidade)
    logger.info("  polaridade do complemento %6d", lexico.entradas_por_complemento)
    logger.info("  pre-processamento ....... %s", VERSAO_PREPROCESSAMENTO)
    logger.info("-" * 66)
    logger.info("  previsao:")
    for classe in CLASSES:
        quantidade = distribuicao.get(classe, 0)
        proporcao = 100 * quantidade / total if total else 0.0
        logger.info("    %-10s %5d  (%5.1f%%)", classe, quantidade, proporcao)
    logger.info("-" * 66)
    logger.info(
        "  sem nenhuma palavra do lexico: %5d  (%.1f%% - viram neutro por ausencia)",
        sem_cobertura,
        100 * sem_cobertura / total if total else 0.0,
    )
    logger.info(
        "  neutro por empate de polaridade: %3d",
        distribuicao.get("neutro", 0) - sem_cobertura,
    )
    logger.info("=" * 66)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument(
        "--lexico",
        type=Path,
        default=ARQUIVO_LEXICO_PADRAO,
        help="arquivo do SentiLex-PT02 (flex por padrao; ver README desta pasta)",
    )
    parser.add_argument("--saida", type=Path, default=ARQUIVO_PREVISOES)
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    if not argumentos.lexico.exists():
        raise SystemExit(
            f"{argumentos.lexico} nao encontrado. O SentiLex-PT02 nao e versionado "
            "(dado de terceiros, 6,9 MB): baixe conforme ml/lexico/README.md."
        )

    lexico = carregar(argumentos.lexico)
    comentarios = asyncio.run(carregar_teste(argumentos.id_execucao))
    if not comentarios:
        raise SystemExit(
            f"nenhum exemplo com split='teste' na execucao {argumentos.id_execucao}. "
            "Rode antes: python -m ml.amostra.sortear_amostra_humana --id-execucao "
            f"{argumentos.id_execucao}"
        )

    previsoes = [
        (id_comentario, classificar(preparar_texto(texto), lexico))
        for id_comentario, texto in comentarios
    ]

    relatar(previsoes, lexico)
    gravar_previsoes(previsoes, argumentos.saida, argumentos.id_execucao)
    gravar_metadados(previsoes, lexico, argumentos.id_execucao, ARQUIVO_METADADOS)


if __name__ == "__main__":
    main()
