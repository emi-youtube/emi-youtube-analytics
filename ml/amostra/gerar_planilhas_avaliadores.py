"""Gera uma planilha por avaliador humano, para a rotulagem ÀS CEGAS.

Três arquivos, mesmo conteúdo, **ordem aleatória diferente em cada um**. A ordem
embaralhada existe para quebrar dois vieses: o de vizinhança (comentários do mesmo
vídeo em sequência se contaminam) e o de fadiga (sem isso, os três avaliadores
cansariam exatamente nos mesmos comentários, e a concordância no fim da planilha
cairia junto — o Kappa mediria cansaço coletivo).

**Sem a coluna `rotulo_fraco`.** Se o avaliador visse o palpite da Gemini, ele
tenderia a concordar, o Kappa subiria artificialmente e o conjunto de teste deixaria
de ser independente — exatamente a circularidade que o CLAUDE.md regra 6 proíbe.

O texto é o **ORIGINAL**, com emoji. É o mesmo que foi para a Gemini: régua igual
dos dois lados é o que torna a comparação honesta.

A régua dos dois lados é o **`ml/rotulagem/manual_rotulagem_v1.md`**. O avaliador lê
o manual inteiro; a Gemini recebe o espelho condensado dele que está em
`prompt_v1.md`. A aba de instruções aponta para o manual, nunca para o prompt:
mandar o avaliador ler o prompt seria dar a ele a versão resumida de uma regra que
existe completa noutro arquivo — e as duas metades do Kappa deixariam de usar a
mesma régua.

Uso:
    python -m ml.amostra.gerar_planilhas_avaliadores --id-execucao 4
"""

import argparse
import asyncio
import logging
import random
import sys

import asyncpg
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ml.config import CLASSES, DIRETORIO_ML, SEMENTE, dsn_postgres

logger = logging.getLogger("planilhas_avaliadores")

AVALIADORES = ("avaliador_1", "avaliador_2", "avaliador_3")

CABECALHO = ("id_comentario", "texto", "rotulo", "duvida", "observacao")

# Fonte unica dos criterios de rotulagem. O `prompt_v1.md` e um espelho condensado
# dela, dirigido a Gemini — o avaliador humano le o manual.
MANUAL = "ml/rotulagem/manual_rotulagem_v1.md"

DIRETORIO_SAIDA = DIRETORIO_ML / "amostra" / "planilhas"

# Excel corta célula acima disto; nenhum comentário do corpus chega perto, mas um
# texto gigante quebraria o arquivo inteiro em silêncio.
MAX_CARACTERES_CELULA = 32000


async def carregar_amostra(conexao: asyncpg.Connection, id_execucao: int) -> list[asyncpg.Record]:
    """A amostra humana: split='teste'. NÃO traz rotulo_fraco de propósito."""
    return await conexao.fetch(
        """
        SELECT e.id_comentario, e.texto
        FROM exemplos_treinamento e
        JOIN comentarios c ON c.id_comentario = e.id_comentario
        JOIN videos v ON v.id_video = c.id_video
        WHERE v.id_execucao = $1 AND e.split = 'teste'
        ORDER BY e.id_comentario
        """,
        id_execucao,
    )


def montar_planilha(linhas: list[tuple[int, str]], avaliador: str):
    livro = Workbook()
    aba = livro.active
    aba.title = "rotulagem"

    aba.append(list(CABECALHO))
    for celula in aba[1]:
        celula.font = Font(bold=True)
        celula.fill = PatternFill("solid", fgColor="DDDDDD")

    for id_comentario, texto in linhas:
        aba.append([id_comentario, texto[:MAX_CARACTERES_CELULA], "", "", ""])

    # Validação por lista: sem isto um "Positivo" ou "pos" digitado à mão entraria
    # no cálculo do Kappa como classe desconhecida, e o erro só apareceria no fim.
    validacao = DataValidation(
        type="list",
        formula1='"{}"'.format(",".join(CLASSES)),
        allow_blank=True,
        showDropDown=False,
    )
    validacao.error = "Use exatamente: " + ", ".join(CLASSES)
    validacao.errorTitle = "Rótulo inválido"
    validacao.prompt = "positivo, negativo ou neutro"
    aba.add_data_validation(validacao)
    validacao.add(f"C2:C{len(linhas) + 1}")

    # "duvida": marca o comentário para discussão no consenso, sem travar a linha.
    duvida = DataValidation(type="list", formula1='"sim,nao"', allow_blank=True, showDropDown=False)
    duvida.prompt = "marque 'sim' se ficou em duvida — sera discutido no consenso"
    aba.add_data_validation(duvida)
    duvida.add(f"D2:D{len(linhas) + 1}")

    larguras = {"A": 14, "B": 90, "C": 12, "D": 10, "E": 40}
    for coluna, largura in larguras.items():
        aba.column_dimensions[coluna].width = largura
    for linha in aba.iter_rows(min_row=2, min_col=2, max_col=2):
        linha[0].alignment = Alignment(wrap_text=True, vertical="top")

    # Congela o cabeçalho: com centenas de linhas, rolar sem isso faz o avaliador
    # perder de vista qual coluna é qual.
    aba.freeze_panes = "A2"

    instrucoes = livro.create_sheet("instrucoes")
    for numero, texto in enumerate(
        [
            f"Planilha de rotulagem — {avaliador}",
            "",
            f"LEIA O MANUAL INTEIRO ANTES DE COMECAR: {MANUAL}",
            "Ele e a fonte unica dos criterios. Na duvida, vale o manual, nao a sua opiniao.",
            "Faca o exercicio de calibracao (Secao 8) antes desta planilha.",
            "",
            "1. Classifique o sentimento SOBRE A CAMPANHA, O PRODUTO OU A MARCA anunciada",
            "   (manual, Secao 4). Entrega, atendimento e preco contam como marca.",
            "2. Use a coluna 'rotulo': positivo, negativo ou neutro (lista suspensa).",
            "3. 'neutro' NAO e o lugar da duvida: e ausencia de avaliacao (manual, Secao 3).",
            "   Caso dificil entre positivo e negativo se resolve pela Secao 5, nao com neutro.",
            "4. Marque 'duvida' = sim quando hesitar, mesmo tendo escolhido uma classe.",
            "5. Use 'observacao' para dizer por que hesitou, em poucas palavras.",
            "6. NAO consulte os outros avaliadores enquanto rotula, e NAO consulte nenhuma IA.",
            "7. Nao pule linhas: linha vazia quebra o calculo do Kappa.",
            "",
            "Trabalhe em blocos de no maximo 50 comentarios, com pausa entre eles.",
            "",
            "A ordem dos comentarios e diferente em cada planilha, de proposito.",
            "Nao compare por numero de linha — o que identifica o comentario e o id_comentario.",
        ],
        start=1,
    ):
        instrucoes.cell(row=numero, column=1, value=texto)
    instrucoes.column_dimensions["A"].width = 100
    instrucoes["A1"].font = Font(bold=True, size=13)

    for aba_qualquer in (aba, instrucoes):
        aba_qualquer.sheet_view.showGridLines = True
    get_column_letter  # noqa: B018 - mantido para clareza do mapa de larguras acima

    return livro


async def gerar(id_execucao: int) -> int:
    conexao = await asyncpg.connect(dsn_postgres())
    try:
        registros = await carregar_amostra(conexao, id_execucao)
    finally:
        await conexao.close()

    if not registros:
        raise SystemExit(
            "Nenhum exemplo com split='teste'. Rode antes: "
            "python -m ml.amostra.sortear_amostra_humana --id-execucao <N>"
        )

    linhas = [(r["id_comentario"], r["texto"]) for r in registros]
    DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)

    logger.info("amostra: %s comentarios", len(linhas))
    for indice, avaliador in enumerate(AVALIADORES):
        # Semente derivada: cada avaliador recebe uma ordem diferente, mas o
        # conjunto das tres ordens e reproduzivel a partir da SEMENTE do projeto.
        sorteio = random.Random(SEMENTE + indice)
        embaralhadas = linhas[:]
        sorteio.shuffle(embaralhadas)

        caminho = DIRETORIO_SAIDA / f"{avaliador}.xlsx"
        montar_planilha(embaralhadas, avaliador).save(caminho)
        logger.info("  %s -> %s (primeiro id: %s)", avaliador, caminho.name, embaralhadas[0][0])

    logger.info("")
    logger.info("planilhas em %s", DIRETORIO_SAIDA)
    logger.info("NAO commite: contem texto de terceiros e o repositorio e publico.")
    return len(linhas)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)
    asyncio.run(gerar(argumentos.id_execucao))


if __name__ == "__main__":
    main()
