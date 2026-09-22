"""Popula EXEMPLOS_TREINAMENTO a partir de uma execução e exporta `ml/dados/corpus.csv`.

Entrada: os COMENTARIOS já coletados por uma execução (worker de coleta do backend).
Saída:   linhas em EXEMPLOS_TREINAMENTO (texto CANÔNICO) + CSV com as duas versões
         do texto.

Qual texto vai para onde (CLAUDE.md Seção 3, "Quem vê qual texto"):

- `exemplos_treinamento.texto` e a coluna `texto` do CSV guardam o **original**, só
  com quebra de linha normalizada e espaço colapsado. É o que o avaliador humano e a
  Gemini leem — rótulo tem que ser dado sobre o que a pessoa escreveu.
- A coluna `texto_modelo` do CSV guarda o resultado de `preparar_texto`: é a entrada
  do BERTimbau, derivada e descartável. Vem junto só para conferência; quem treina
  pode recalculá-la a qualquer momento a partir do canônico.
- `versao_preprocessamento` viaja no CSV para que uma amostra rotulada nunca fique
  órfã da versão que a gerou.

Ordem das etapas (importa para os números baterem):

1. lê os comentários da execução, ordenados por id_comentario;
2. normaliza espaço -> texto canônico;
3. descarta o que ficou vazio;
4. descarta o que não está em alfabeto latino;
5. aplica o teto por vídeo, amostrando com semente fixa;
6. grava com `split` NULO.

O descarte vem ANTES do teto: amostrar primeiro deixaria o vídeo com menos de 400
exemplos úteis, porque parte da amostra morreria nos passos seguintes.

O `split` sai NULO de propósito — ver `SPLIT_NAO_ATRIBUIDO` abaixo.

Reprodutibilidade: toda aleatoriedade sai de `random.Random(SEMENTE)` e a ordenação
de entrada é determinística, então reexecutar sobre a mesma execução seleciona os
mesmos comentários.

O `id_exemplo` é a única coisa que muda entre execuções: a coluna é `serial`, e a
reinserção consome novos valores da sequência. Portanto **a chave estável do corpus
é `id_comentario`, não `id_exemplo`** — é por ela que a rotulagem fraca e a validação
humana devem casar suas planilhas.

Uso:
    python -m ml.exportacao.exportar_corpus --id-execucao 4
"""

import argparse
import asyncio
import csv
import logging
import random
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

import asyncpg
from preprocessamento import VERSAO as VERSAO_PREPROCESSAMENTO
from preprocessamento import normalizar_espacos, preparar_texto

from ml.config import DIRETORIO_DADOS, SEMENTE, dsn_postgres

logger = logging.getLogger("exportar_corpus")

# Teto por vídeo. Sem ele, os dois vídeos de maior volume dominariam o corpus e o
# modelo aprenderia o vocabulário dessas campanhas em vez de sentimento.
TETO_POR_VIDEO = 400

# Fração mínima de letras latinas para o comentário entrar no corpus. O modelo é
# BERTimbau, treinado em português: um comentário em coreano não tem como ser
# classificado nem rotulado pela equipe, e no tokenizer ele vira [UNK] puro.
# Meio a meio passa — o corte é para texto MAJORITARIAMENTE de outro alfabeto.
FRACAO_MINIMA_LATINA = 0.5

# O split nasce NULO. Sortear a partição aqui, antes de existir rótulo, faria o
# conjunto de teste sair de dentro do corpus de rótulo fraco — a circularidade da
# Seção 4.1.2, e o contrário do CLAUDE.md regra 6 ("o teste é só humano").
# A atribuição acontece DEPOIS da rotulagem fraca: a amostra humana é sorteada
# estratificada pelo rótulo fraco e vira `teste`; o resto vai 85/15.
SPLIT_NAO_ATRIBUIDO = None

ARQUIVO_SAIDA = DIRETORIO_DADOS / "corpus.csv"
COLUNAS_CSV = (
    "id_exemplo",
    "id_comentario",
    "id_video",
    "texto",
    "texto_modelo",
    "versao_preprocessamento",
)


@dataclass
class Contagens:
    """Placar de cada etapa, para o relatório da Sprint 1."""

    brutos: int = 0
    descartados_vazios: int = 0
    descartados_idioma: int = 0
    normalizados_quebra: int = 0
    texto_modelo_diferente: int = 0
    descartados_teto: int = 0
    exportados: int = 0

    def relatar(self, por_video: dict[str, tuple[int, int]]) -> None:
        logger.info("=" * 62)
        logger.info("comentarios brutos na execucao ............ %5d", self.brutos)
        logger.info("descartados: texto vazio/so espacos ....... %5d", self.descartados_vazios)
        logger.info("descartados: alfabeto nao latino .......... %5d", self.descartados_idioma)
        logger.info(
            "descartados: teto de %d por video ........ %5d", TETO_POR_VIDEO, self.descartados_teto
        )
        logger.info("EXPORTADOS ................................ %5d", self.exportados)
        logger.info("-" * 62)
        logger.info("normalizados: quebra de linha -> espaco ... %5d", self.normalizados_quebra)
        # Conta emoji E troca tipografica: é o total de linhas em que a entrada do
        # modelo não é igual ao que a pessoa escreveu.
        logger.info("texto_modelo != canonico .................. %5d", self.texto_modelo_diferente)
        logger.info("pre-processamento versao .................. %5s", VERSAO_PREPROCESSAMENTO)
        logger.info("=" * 62)
        logger.info("%-14s %8s %8s %8s", "video", "bruto", "exportado", "cortado")
        for youtube_id, (bruto, exportado) in sorted(
            por_video.items(), key=lambda item: -item[1][1]
        ):
            logger.info("%-14s %8d %8d %8d", youtube_id, bruto, exportado, bruto - exportado)


def e_majoritariamente_latino(texto: str) -> bool:
    """`True` se pelo menos metade das LETRAS do texto for do alfabeto latino.

    Conta só letras: número, emoji e pontuação não dizem nada sobre o idioma, e um
    comentário como "10/10 😂" não pode ser descartado por não ter letra nenhuma.
    Texto sem letra alguma passa — a ausência de letra não é evidência de outro
    alfabeto.

    O teste é por SCRIPT (o nome Unicode do caractere começa com "LATIN"), não por
    idioma: "não", "coração" e "über" são latinos; 한국어 e русский não são.
    """
    letras = [caractere for caractere in texto if unicodedata.category(caractere).startswith("L")]
    if not letras:
        return True
    latinas = sum(1 for letra in letras if unicodedata.name(letra, "").startswith("LATIN"))
    return latinas / len(letras) >= FRACAO_MINIMA_LATINA


async def carregar_comentarios(
    conexao: asyncpg.Connection, id_execucao: int
) -> list[asyncpg.Record]:
    """Comentários da execução, em ordem determinística (a amostragem depende disso)."""
    return await conexao.fetch(
        """
        SELECT c.id_comentario, c.id_video, v.youtube_video_id, c.texto
        FROM comentarios c
        JOIN videos v ON v.id_video = c.id_video
        WHERE v.id_execucao = $1
        ORDER BY c.id_comentario
        """,
        id_execucao,
    )


async def exportar(id_execucao: int) -> Contagens:
    sorteio = random.Random(SEMENTE)
    contagens = Contagens()

    conexao = await asyncpg.connect(dsn_postgres())
    try:
        registros = await carregar_comentarios(conexao, id_execucao)
        contagens.brutos = len(registros)
        if not registros:
            raise SystemExit(f"Execução {id_execucao} não tem comentários coletados.")

        logger.info(
            "id_execucao=%s comentarios brutos=%s preprocessamento=%s",
            id_execucao,
            contagens.brutos,
            VERSAO_PREPROCESSAMENTO,
        )

        # --- etapas 2 a 4: canônico, descartes ---
        por_video: dict[int, list[tuple[int, str]]] = defaultdict(list)
        youtube_id_de: dict[int, str] = {}
        brutos_por_video: Counter[str] = Counter()

        for registro in registros:
            youtube_id_de[registro["id_video"]] = registro["youtube_video_id"]
            brutos_por_video[registro["youtube_video_id"]] += 1

            bruto = registro["texto"] or ""
            if "\n" in bruto or "\r" in bruto:
                contagens.normalizados_quebra += 1

            # Texto CANÔNICO: só espaço. É este que vai para o banco e para o CSV.
            texto = normalizar_espacos(bruto)
            if not texto:
                contagens.descartados_vazios += 1
                continue
            if not e_majoritariamente_latino(texto):
                contagens.descartados_idioma += 1
                continue

            por_video[registro["id_video"]].append((registro["id_comentario"], texto))

        # --- etapa 5: teto por vídeo, com semente fixa ---
        selecionados: list[tuple[int, int, str]] = []
        for id_video in sorted(por_video):
            comentarios = por_video[id_video]
            if len(comentarios) > TETO_POR_VIDEO:
                amostra = sorteio.sample(comentarios, TETO_POR_VIDEO)
                contagens.descartados_teto += len(comentarios) - TETO_POR_VIDEO
                # Reordena: `sample` devolve em ordem de sorteio, e o corpus fica
                # mais fácil de conferir com os ids crescentes.
                amostra.sort()
            else:
                amostra = comentarios
            selecionados.extend(
                (id_comentario, id_video, texto) for id_comentario, texto in amostra
            )

        selecionados.sort()
        contagens.exportados = len(selecionados)

        # --- etapa 6: grava EXEMPLOS_TREINAMENTO (texto CANÔNICO) ---
        # Idempotente: reexecutar não duplica o corpus. Só apaga os exemplos desta
        # execução; exemplos de outra origem (ou já rotulados à mão) ficam intactos.
        apagados = await conexao.execute(
            """
            DELETE FROM exemplos_treinamento e
            USING comentarios c
            JOIN videos v ON v.id_video = c.id_video
            WHERE e.id_comentario = c.id_comentario AND v.id_execucao = $1
            """,
            id_execucao,
        )
        logger.info("exemplos anteriores desta execucao removidos (%s)", apagados)

        ids_comentario = [item[0] for item in selecionados]
        textos = [item[2] for item in selecionados]
        splits = [SPLIT_NAO_ATRIBUIDO] * len(selecionados)

        inseridos = await conexao.fetch(
            """
            INSERT INTO exemplos_treinamento (id_comentario, texto, split)
            SELECT * FROM unnest($1::int[], $2::text[], $3::varchar[])
            RETURNING id_exemplo, id_comentario
            """,
            ids_comentario,
            textos,
            splits,
        )
        logger.info("exemplos_treinamento populada: %s linha(s)", len(inseridos))
    finally:
        await conexao.close()

    # --- CSV: canônico + derivado, lado a lado ---
    id_exemplo_de = {r["id_comentario"]: r["id_exemplo"] for r in inseridos}

    DIRETORIO_DADOS.mkdir(parents=True, exist_ok=True)
    # newline="" é exigência do csv no Windows: sem isso sai \r\r\n entre as linhas.
    with ARQUIVO_SAIDA.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(COLUNAS_CSV)
        for id_comentario, id_video, texto in selecionados:
            texto_modelo = preparar_texto(texto)
            if texto_modelo != texto:
                contagens.texto_modelo_diferente += 1
            escritor.writerow(
                [
                    id_exemplo_de[id_comentario],
                    id_comentario,
                    id_video,
                    texto,
                    texto_modelo,
                    VERSAO_PREPROCESSAMENTO,
                ]
            )

    logger.info("csv escrito em %s", ARQUIVO_SAIDA)

    exportados_por_video: Counter[str] = Counter()
    for _, id_video, _ in selecionados:
        exportados_por_video[youtube_id_de[id_video]] += 1
    contagens.relatar(
        {
            youtube_id: (brutos_por_video[youtube_id], exportados_por_video[youtube_id])
            for youtube_id in brutos_por_video
        }
    )

    logger.info(
        "splits: todos NULL (%d) — partição será atribuída depois da rotulagem fraca",
        len(splits),
    )
    return contagens


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)
    asyncio.run(exportar(argumentos.id_execucao))


if __name__ == "__main__":
    main()
