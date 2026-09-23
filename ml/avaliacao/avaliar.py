"""Compara qualquer conjunto de previsões contra o `rotulo_humano` e gera o Capítulo 5.

A matemática mora em `metricas.py` e o desenho em `graficos.py`; aqui fica o que toca
banco, CSV e disco.

**O gabarito é sempre humano** (CLAUDE.md regra 6). Ele sai de
`exemplos_treinamento.rotulo_humano`, que só existe depois da validação humana e da
apuração do Kappa. A Gemini entra aqui como **método avaliado** — o `rotulo_fraco`
dos mesmos 334 comentários vira uma coluna de previsão como qualquer outra —, nunca
como referência. É a diferença entre medir a rotulagem fraca e validar-se com ela.

Empate 1-1-1 fica de fora: `rotulo_humano` é NULO até a reunião de consenso decidir,
e comentário sem gabarito não pode entrar em nenhuma métrica. Quantos ficaram de
fora aparece no relatório — é número de Capítulo 5, não detalhe de execução.

**Um conjunto de previsões é um CSV** com `id_comentario` e uma coluna de rótulo
(`previsto`, `rotulo` ou `sentimento`). Qualquer método que produza isso entra na
comparação sem tocar neste arquivo: hoje o léxico, amanhã o BERTimbau.

**Nada é gravado no banco.** A leitura é a única coisa que este script faz lá.

Uso:
    # ensaio de hoje: gabarito sintetico, o real ainda nao voltou
    python -m ml.avaliacao.avaliar --gabarito ensaio/gabarito.csv \\
        --previsoes lexico=ml/dados/previsoes_lexico.csv --saida ensaio/saida

    # o dia em que o gabarito voltar
    python -m ml.avaliacao.avaliar --id-execucao 4 \\
        --previsoes lexico=ml/dados/previsoes_lexico.csv --gemini
"""

import argparse
import asyncio
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from ml.avaliacao.metricas import (
    CONFIANCA,
    REAMOSTRAGENS,
    SEMENTE,
    Metricas,
    avaliar_previsoes,
    intervalo_bootstrap,
)
from ml.config import CLASSES, DIRETORIO_ML, dsn_postgres

logger = logging.getLogger("avaliacao")

DIRETORIO_SAIDA = DIRETORIO_ML / "avaliacao" / "saida"

SPLIT_TESTE = "teste"

# Nomes aceitos para a coluna de rótulo, em ordem de preferência. Aceitar mais de um
# é o que torna "qualquer conjunto de previsões" verdade: o CSV do léxico chama de
# `previsto`, um export de notebook do Colab provavelmente chamará de `sentimento`.
COLUNAS_ROTULO = ("previsto", "rotulo", "rotulo_humano", "sentimento")

COLUNA_ID = "id_comentario"

# Nome do método da Gemini no relatório. Fica explícito que a fonte é o rótulo fraco:
# ninguém deve ler a linha dela como "a Gemini foi consultada de novo".
METODO_GEMINI = "gemini (rotulo_fraco)"


@dataclass
class Problema:
    """Uma falha de validação, com endereço suficiente para consertar o arquivo."""

    fonte: str
    linha: int | None
    id_comentario: int | None
    descricao: str

    def __str__(self) -> str:
        onde = self.fonte
        if self.linha is not None:
            onde += f" linha {self.linha}"
        if self.id_comentario is not None:
            onde += f" (id {self.id_comentario})"
        return f"{onde}: {self.descricao}"


@dataclass(frozen=True)
class Avaliacao:
    """O resultado de um método: métricas pontuais mais o intervalo do bootstrap."""

    metodo: str
    origem: str
    metricas: Metricas
    intervalos: dict[str, tuple[float, float]]


def ler_csv(caminho: Path, fonte: str) -> tuple[dict[int, str], list[Problema]]:
    """Lê um CSV de rótulos. Não para no primeiro erro: junta todos.

    Parar no primeiro faria quem gerou o arquivo consertar uma linha, rodar de novo,
    descobrir a próxima — o mesmo motivo que vale na leitura das planilhas dos
    avaliadores (`ml/concordancia/calcular_concordancia.py`).
    """
    if not caminho.exists():
        return {}, [Problema(fonte, None, None, f"arquivo nao encontrado: {caminho}")]

    rotulos: dict[int, str] = {}
    problemas: list[Problema] = []

    with caminho.open(encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        cabecalho = leitor.fieldnames or []
        if COLUNA_ID not in cabecalho:
            return {}, [Problema(fonte, 1, None, f"csv sem a coluna '{COLUNA_ID}'")]

        coluna = next((nome for nome in COLUNAS_ROTULO if nome in cabecalho), None)
        if coluna is None:
            return {}, [
                Problema(
                    fonte,
                    1,
                    None,
                    f"csv sem coluna de rotulo (use uma de: {', '.join(COLUNAS_ROTULO)})",
                )
            ]

        for numero, linha in enumerate(leitor, start=2):
            bruto_id = (linha.get(COLUNA_ID) or "").strip()
            try:
                id_comentario = int(bruto_id)
            except ValueError:
                problemas.append(
                    Problema(fonte, numero, None, f"id_comentario invalido: {bruto_id!r}")
                )
                continue

            rotulo = (linha.get(coluna) or "").strip()
            if not rotulo:
                problemas.append(Problema(fonte, numero, id_comentario, "rotulo vazio"))
                continue
            if rotulo not in CLASSES:
                problemas.append(
                    Problema(
                        fonte,
                        numero,
                        id_comentario,
                        f"rotulo fora das classes: {rotulo!r} (use {', '.join(CLASSES)})",
                    )
                )
                continue
            if id_comentario in rotulos:
                problemas.append(
                    Problema(fonte, numero, id_comentario, "id_comentario repetido no csv")
                )
                continue
            rotulos[id_comentario] = rotulo

    return rotulos, problemas


async def ler_do_banco(id_execucao: int, coluna: str) -> dict[int, str | None]:
    """Lê uma coluna de rótulo do conjunto de teste.

    `coluna` é interpolada na query porque é escolhida pelo código (`rotulo_humano`
    ou `rotulo_fraco`), nunca por entrada do usuário — a lista fechada abaixo é o que
    garante isso.
    """
    if coluna not in {"rotulo_humano", "rotulo_fraco"}:
        raise ValueError(f"coluna nao permitida: {coluna!r}")

    conexao = await asyncpg.connect(dsn_postgres())
    try:
        registros = await conexao.fetch(
            f"""
            SELECT e.id_comentario, e.{coluna} AS rotulo
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
    return {registro["id_comentario"]: registro["rotulo"] for registro in registros}


def validar_cobertura(
    gabarito: dict[int, str], previsoes: dict[int, str], fonte: str
) -> list[Problema]:
    """Todo comentário do gabarito precisa ter previsão. Sobra é aviso, falta é erro.

    Previsão a mais (um método que classificou o corpus inteiro, por exemplo) é
    ignorada em silêncio no cálculo — o conjunto avaliado é o do gabarito. Previsão a
    menos mudaria o `n` do método sem avisar, e dois métodos medidos em conjuntos
    diferentes não são comparáveis.
    """
    return [
        Problema(fonte, None, id_comentario, "sem previsao para este comentario")
        for id_comentario in sorted(set(gabarito) - set(previsoes))
    ]


def avaliar_metodo(
    metodo: str,
    origem: str,
    gabarito: dict[int, str],
    previsoes: dict[int, str],
    reamostragens: int,
) -> Avaliacao:
    """Alinha gabarito e previsão por `id_comentario` e calcula tudo.

    A ordenação por id é o que garante que os dois lados falam do mesmo comentário —
    CSV de método nenhum tem obrigação de sair na mesma ordem.
    """
    ids = sorted(gabarito)
    verdadeiros = [gabarito[id_comentario] for id_comentario in ids]
    previstos = [previsoes[id_comentario] for id_comentario in ids]

    return Avaliacao(
        metodo=metodo,
        origem=origem,
        metricas=avaliar_previsoes(verdadeiros, previstos, CLASSES),
        intervalos=intervalo_bootstrap(
            verdadeiros, previstos, CLASSES, reamostragens=reamostragens
        ),
    )


def relatar(avaliacoes: list[Avaliacao], excluidos: int) -> None:
    """Relatório de console. É o que vira as tabelas do Capítulo 5."""
    total = avaliacoes[0].metricas.total

    logger.info("")
    logger.info("=" * 78)
    logger.info("AVALIACAO CONTRA O GABARITO HUMANO - %s comentarios", total)
    logger.info("=" * 78)
    if excluidos:
        logger.info(
            "  %s comentario(s) fora: sem rotulo_humano (empate 1-1-1 aguardando consenso)",
            excluidos,
        )

    logger.info("")
    logger.info(
        "%-24s %9s %9s %9s %9s", "metodo", "acuracia", "P macro", "R macro", "F1 macro"
    )
    logger.info("-" * 78)
    for avaliacao in avaliacoes:
        metricas = avaliacao.metricas
        logger.info(
            "%-24s %9.4f %9.4f %9.4f %9.4f",
            avaliacao.metodo,
            metricas.acuracia,
            metricas.precisao_macro,
            metricas.revocacao_macro,
            metricas.f1_macro,
        )

    logger.info("")
    logger.info("F1 por classe, com IC de %.0f%% (bootstrap):", 100 * CONFIANCA)
    for avaliacao in avaliacoes:
        logger.info("")
        logger.info("  %s", avaliacao.metodo)
        for classe in CLASSES:
            metricas = avaliacao.metricas.por_classe[classe]
            intervalo = avaliacao.intervalos.get(classe)
            faixa = f"[{intervalo[0]:.4f}; {intervalo[1]:.4f}]" if intervalo else "[indefinido]"
            logger.info(
                "    %-10s P=%.4f  R=%.4f  F1=%.4f  %-22s n=%d",
                classe,
                metricas.precisao,
                metricas.revocacao,
                metricas.f1,
                faixa,
                metricas.suporte,
            )
        macro = avaliacao.intervalos.get("macro")
        if macro:
            logger.info(
                "    %-10s F1=%.4f  [%.4f; %.4f]",
                "MACRO",
                avaliacao.metricas.f1_macro,
                macro[0],
                macro[1],
            )

    logger.info("")
    logger.info("Matriz de confusao (linha = gabarito, coluna = previsto):")
    largura = max(len(classe) for classe in CLASSES)
    for avaliacao in avaliacoes:
        logger.info("")
        logger.info("  %s", avaliacao.metodo)
        logger.info("  %s %s", " " * largura, "  ".join(f"{classe:>10}" for classe in CLASSES))
        for linha in CLASSES:
            celulas = "  ".join(
                f"{avaliacao.metricas.confusao[linha][coluna]:>10}" for coluna in CLASSES
            )
            logger.info("  %-*s %s", largura, linha, celulas)

    logger.info("")
    logger.info("=" * 78)
    melhor = max(avaliacoes, key=lambda avaliacao: avaliacao.metricas.f1_macro)
    logger.info("maior F1 macro: %s (%.4f)", melhor.metodo, melhor.metricas.f1_macro)
    if len(avaliacoes) > 1:
        logger.info(
            "Intervalos que se sobrepoem NAO demonstram diferenca entre os metodos - "
            "compare as faixas, nao so os pontos."
        )
    logger.info("=" * 78)


def _linha_metricas(avaliacao: Avaliacao, classe: str) -> dict[str, object]:
    """Uma linha da tabela longa: método x classe."""
    metricas = avaliacao.metricas.por_classe[classe]
    intervalo = avaliacao.intervalos.get(classe)
    return {
        "metodo": avaliacao.metodo,
        "classe": classe,
        "precisao": round(metricas.precisao, 4),
        "revocacao": round(metricas.revocacao, 4),
        "f1": round(metricas.f1, 4),
        "ic95_inferior": round(intervalo[0], 4) if intervalo else "",
        "ic95_superior": round(intervalo[1], 4) if intervalo else "",
        "suporte": metricas.suporte,
    }


def gravar_tabelas(avaliacoes: list[Avaliacao], diretorio: Path) -> None:
    """Tabelas prontas para colar no Capítulo 5: Markdown para ler, CSV para reusar.

    Markdown porque o documento acadêmico é escrito fora daqui e a tabela precisa
    atravessar um copiar/colar sem perder alinhamento; CSV porque a mesma tabela vai
    querer virar planilha na apresentação.
    """
    diretorio.mkdir(parents=True, exist_ok=True)

    linhas = [_linha_metricas(avaliacao, classe) for avaliacao in avaliacoes for classe in CLASSES]
    with (diretorio / "tabela_metricas.csv").open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)

    partes: list[str] = []
    partes.append("# Capitulo 5 - tabelas\n")
    partes.append(f"\nGabarito humano, {avaliacoes[0].metricas.total} comentarios.\n")

    partes.append("\n## Tabela 1 - desempenho geral por metodo\n\n")
    partes.append(
        "| metodo | acuracia | precisao macro | revocacao macro | F1 macro "
        "| IC 95% (F1 macro) |\n"
    )
    partes.append("|---|---|---|---|---|---|\n")
    for avaliacao in avaliacoes:
        metricas = avaliacao.metricas
        macro = avaliacao.intervalos.get("macro")
        faixa = f"[{macro[0]:.3f}; {macro[1]:.3f}]" if macro else "-"
        partes.append(
            f"| {avaliacao.metodo} | {metricas.acuracia:.3f} | {metricas.precisao_macro:.3f} "
            f"| {metricas.revocacao_macro:.3f} | **{metricas.f1_macro:.3f}** | {faixa} |\n"
        )

    partes.append("\n## Tabela 2 - desempenho por classe (IC 95% do F1, bootstrap)\n\n")
    partes.append("| metodo | classe | precisao | revocacao | F1 | IC 95% | suporte |\n")
    partes.append("|---|---|---|---|---|---|---|\n")
    for linha in linhas:
        faixa = (
            f"[{linha['ic95_inferior']:.3f}; {linha['ic95_superior']:.3f}]"
            if linha["ic95_inferior"] != ""
            else "-"
        )
        partes.append(
            f"| {linha['metodo']} | {linha['classe']} | {linha['precisao']:.3f} "
            f"| {linha['revocacao']:.3f} | {linha['f1']:.3f} | {faixa} | {linha['suporte']} |\n"
        )

    partes.append("\n## Tabela 3 - matrizes de confusao (linha = gabarito, coluna = previsto)\n")
    for avaliacao in avaliacoes:
        partes.append(f"\n### {avaliacao.metodo}\n\n")
        partes.append("| gabarito \\ previsto | " + " | ".join(CLASSES) + " |\n")
        partes.append("|---" * (len(CLASSES) + 1) + "|\n")
        for classe in CLASSES:
            celulas = " | ".join(
                str(avaliacao.metricas.confusao[classe][coluna]) for coluna in CLASSES
            )
            partes.append(f"| **{classe}** | {celulas} |\n")

    (diretorio / "tabela_metricas.md").write_text("".join(partes), encoding="utf-8")
    logger.info("tabelas -> %s", diretorio / "tabela_metricas.md")


def gravar_relatorio(
    avaliacoes: list[Avaliacao],
    excluidos: int,
    origem_gabarito: str,
    reamostragens: int,
    caminho: Path,
) -> None:
    """JSON de agregados. Só número e nome de método: nenhum texto de terceiros."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "data_utc": datetime.now(UTC).isoformat(),
        "gabarito": origem_gabarito,
        "total_avaliado": avaliacoes[0].metricas.total,
        "excluidos_sem_rotulo_humano": excluidos,
        "bootstrap": {
            "reamostragens": reamostragens,
            "confianca": CONFIANCA,
            "semente": SEMENTE,
            "metodo": "percentil",
        },
        "metodos": [
            {
                "metodo": avaliacao.metodo,
                "origem": avaliacao.origem,
                "acuracia": avaliacao.metricas.acuracia,
                "precisao_macro": avaliacao.metricas.precisao_macro,
                "revocacao_macro": avaliacao.metricas.revocacao_macro,
                "f1_macro": avaliacao.metricas.f1_macro,
                "ic95_f1_macro": avaliacao.intervalos.get("macro"),
                "por_classe": {
                    classe: {
                        "precisao": metricas.precisao,
                        "revocacao": metricas.revocacao,
                        "f1": metricas.f1,
                        "ic95_f1": avaliacao.intervalos.get(classe),
                        "suporte": metricas.suporte,
                        "verdadeiros_positivos": metricas.verdadeiros_positivos,
                        "falsos_positivos": metricas.falsos_positivos,
                        "falsos_negativos": metricas.falsos_negativos,
                    }
                    for classe, metricas in avaliacao.metricas.por_classe.items()
                },
                "matriz_confusao": avaliacao.metricas.confusao,
            }
            for avaliacao in avaliacoes
        ],
    }
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("relatorio -> %s", caminho)


def _carregar_fontes(
    argumentos: argparse.Namespace,
) -> tuple[dict[int, str], str, int, list[tuple[str, str, dict[int, str]]], list[Problema]]:
    """Carrega gabarito e métodos, acumulando problemas em vez de estourar na hora."""
    problemas: list[Problema] = []
    metodos: list[tuple[str, str, dict[int, str]]] = []

    if argumentos.gabarito:
        bruto, encontrados = ler_csv(argumentos.gabarito, "gabarito")
        problemas.extend(encontrados)
        gabarito = bruto
        origem_gabarito = f"csv: {argumentos.gabarito}"
        excluidos = 0
    else:
        if argumentos.id_execucao is None:
            raise SystemExit("informe --id-execucao (gabarito do banco) ou --gabarito <csv>")
        do_banco = asyncio.run(ler_do_banco(argumentos.id_execucao, "rotulo_humano"))
        gabarito = {
            id_comentario: rotulo for id_comentario, rotulo in do_banco.items() if rotulo
        }
        excluidos = len(do_banco) - len(gabarito)
        origem_gabarito = (
            "banco: exemplos_treinamento.rotulo_humano "
            f"(execucao {argumentos.id_execucao})"
        )

    for especificacao in argumentos.previsoes:
        if "=" not in especificacao:
            raise SystemExit(f"--previsoes espera nome=caminho.csv, veio {especificacao!r}")
        nome, caminho = especificacao.split("=", 1)
        rotulos, encontrados = ler_csv(Path(caminho), nome)
        problemas.extend(encontrados)
        metodos.append((nome, f"csv: {caminho}", rotulos))

    if argumentos.gemini:
        if argumentos.id_execucao is None:
            raise SystemExit("--gemini le o rotulo_fraco do banco e exige --id-execucao")
        do_banco = asyncio.run(ler_do_banco(argumentos.id_execucao, "rotulo_fraco"))
        rotulos = {
            id_comentario: rotulo for id_comentario, rotulo in do_banco.items() if rotulo
        }
        metodos.append(
            (
                METODO_GEMINI,
                f"banco: exemplos_treinamento.rotulo_fraco (execucao {argumentos.id_execucao})",
                rotulos,
            )
        )

    return gabarito, origem_gabarito, excluidos, metodos, problemas


def executar(argumentos: argparse.Namespace) -> tuple[list[Avaliacao], int, str]:
    """Carrega, valida e avalia. Estoura antes de calcular se a validação falhar."""
    gabarito, origem_gabarito, excluidos, metodos, problemas = _carregar_fontes(argumentos)

    if not metodos:
        raise SystemExit(
            "nenhum metodo para avaliar: use --previsoes nome=arquivo.csv e/ou --gemini"
        )

    if gabarito:
        for nome, _, rotulos in metodos:
            problemas.extend(validar_cobertura(gabarito, rotulos, nome))

    if problemas:
        logger.error("")
        logger.error("VALIDACAO FALHOU - %s problema(s). Nada foi calculado.", len(problemas))
        for problema in problemas[:50]:
            logger.error("  %s", problema)
        if len(problemas) > 50:
            logger.error("  ... e mais %s", len(problemas) - 50)
        raise SystemExit(1)

    if not gabarito:
        raise SystemExit(
            "gabarito vazio: nenhum exemplo com rotulo_humano. Rode antes "
            "`python -m ml.concordancia.calcular_concordancia --gravar`, ou use "
            "--gabarito <csv> para o ensaio com gabarito sintetico."
        )

    avaliacoes = [
        avaliar_metodo(nome, origem, gabarito, rotulos, argumentos.reamostragens)
        for nome, origem, rotulos in metodos
    ]
    return avaliacoes, excluidos, origem_gabarito


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, default=None)
    parser.add_argument(
        "--gabarito",
        type=Path,
        default=None,
        help="csv de gabarito (ensaio); sem ele, le rotulo_humano do banco",
    )
    parser.add_argument(
        "--previsoes",
        action="append",
        default=[],
        metavar="nome=arquivo.csv",
        help="conjunto de previsoes a avaliar; pode repetir",
    )
    parser.add_argument(
        "--gemini",
        action="store_true",
        help="avalia o rotulo_fraco da Gemini como um metodo (exige --id-execucao)",
    )
    parser.add_argument("--saida", type=Path, default=DIRETORIO_SAIDA)
    parser.add_argument("--reamostragens", type=int, default=REAMOSTRAGENS)
    parser.add_argument(
        "--sem-graficos", action="store_true", help="so tabelas (nao exige matplotlib)"
    )
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    avaliacoes, excluidos, origem_gabarito = executar(argumentos)

    relatar(avaliacoes, excluidos)
    gravar_tabelas(avaliacoes, argumentos.saida)
    gravar_relatorio(
        avaliacoes,
        excluidos,
        origem_gabarito,
        argumentos.reamostragens,
        argumentos.saida / "resultado_avaliacao.json",
    )

    if argumentos.sem_graficos:
        return

    # Import tardio: quem só quer as tabelas não precisa do matplotlib instalado.
    from ml.avaliacao.graficos import gerar_figuras

    gerar_figuras(avaliacoes, argumentos.saida / "figuras")


if __name__ == "__main__":
    main()
