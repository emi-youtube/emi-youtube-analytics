"""Mede o vazamento entre treino, validação e teste — sem alterar dado nenhum.

Três perguntas, com a régua de `ml/avaliacao/gemeos.py` (exato e quase):

(a) quantos dos 334 do teste têm gêmeo nos 2.200 de treino + validação;
(b) quantos da validação têm gêmeo no treino;
(c) quantos do treino têm gêmeo dentro do próprio treino.

Depois recalcula as métricas da rodada 1 no teste — léxico, BERTimbau e Gemini —
separando "com gêmeo" e "sem gêmeo", com IC por bootstrap. **Léxico e Gemini não
treinam com o corpus**, e por isso são o controle: se eles também acertam mais no
grupo "com gêmeo", o grupo é só mais fácil (comentário curto e genérico); o vazamento
do BERTimbau é o que sobra além disso.

A partição é reconstruída como o treino a fez (`dividir_estratificado`, semente 42):
1.870 / 330. Nada é gravado no banco.

**O que é versionado não tem texto.** `saida_vazamento/` guarda contagens, ids e
métricas. Os exemplos de cada nível (`--exemplos`, 5 por padrão) saem só no console:
são texto de terceiros, e o repositório é público.

Uso:
    python -m ml.avaliacao.vazamento --id-execucao 4
    python -m ml.avaliacao.vazamento --id-execucao 4 \\
        --previsoes tfidf_logreg=ml/dados/previsoes_baseline.csv
"""

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
from preprocessamento import preparar_texto

from ml.avaliacao.avaliar import (
    METODO_GEMINI,
    Avaliacao,
    avaliar_metodo,
    ler_csv,
    validar_cobertura,
)
from ml.avaliacao.gemeos import (
    LIMIAR_QUASE,
    NIVEL_EXATO,
    NIVEL_QUASE,
    TAMANHO_NGRAMA,
    Gemeo,
    buscar_gemeos,
    jaccard,
    ngramas,
    normalizar,
)
from ml.avaliacao.metricas import CONFIANCA, REAMOSTRAGENS, SEMENTE
from ml.config import DIRETORIO_DADOS, DIRETORIO_ML, dsn_postgres
from ml.treino.dados import Exemplo, dividir_estratificado

logger = logging.getLogger("vazamento")

DIRETORIO_SAIDA = DIRETORIO_ML / "avaliacao" / "saida_vazamento"

PREVISOES_PADRAO = (
    f"lexico={DIRETORIO_DADOS / 'previsoes_lexico.csv'}",
    f"bertimbau={DIRETORIO_DADOS / 'previsoes_bertimbau.csv'}",
)

# Comentário "curto": até três palavras depois de normalizar. É onde o gêmeo exato
# é quase inevitável ("Parabéns", "Que carro lindo") e não indica cópia nenhuma.
PALAVRAS_CURTO = 3


@dataclass(frozen=True)
class Comentario:
    id_comentario: int
    id_video: int
    texto: str
    texto_modelo: str
    split: str | None
    rotulo_fraco: str | None
    rotulo_humano: str | None


async def carregar(id_execucao: int) -> list[Comentario]:
    """Todos os comentários do corpus da execução, com vídeo, partição e rótulos."""
    conexao = await asyncpg.connect(dsn_postgres())
    try:
        registros = await conexao.fetch(
            """
            SELECT e.id_comentario, c.id_video, e.texto, e.split,
                   e.rotulo_fraco, e.rotulo_humano
            FROM exemplos_treinamento e
            JOIN comentarios c ON c.id_comentario = e.id_comentario
            JOIN videos v ON v.id_video = c.id_video
            WHERE v.id_execucao = $1
            ORDER BY e.id_comentario
            """,
            id_execucao,
        )
    finally:
        await conexao.close()
    return [
        Comentario(
            id_comentario=registro["id_comentario"],
            id_video=registro["id_video"],
            texto=registro["texto"],
            texto_modelo=preparar_texto(registro["texto"]),
            split=registro["split"],
            rotulo_fraco=registro["rotulo_fraco"],
            rotulo_humano=registro["rotulo_humano"],
        )
        for registro in registros
    ]


def separar(
    comentarios: list[Comentario],
) -> tuple[list[Comentario], list[Comentario], list[Comentario]]:
    """Treino, validação e teste — a partição exata do treino da rodada 1."""
    pool = [c for c in comentarios if c.split is None and c.rotulo_fraco]
    particao = dividir_estratificado(
        [Exemplo(c.id_comentario, c.texto, c.texto_modelo, c.rotulo_fraco) for c in pool]
    )
    ids_treino = {exemplo.id_comentario for exemplo in particao.treino}
    ids_validacao = {exemplo.id_comentario for exemplo in particao.validacao}
    return (
        [c for c in pool if c.id_comentario in ids_treino],
        [c for c in pool if c.id_comentario in ids_validacao],
        [c for c in comentarios if c.split == "teste"],
    )


def _pares(comentarios: list[Comentario]) -> list[tuple[int, str]]:
    return [(c.id_comentario, c.texto_modelo) for c in comentarios]


def _curto(comentario: Comentario) -> bool:
    return len(normalizar(comentario.texto_modelo).split()) <= PALAVRAS_CURTO


def resumir_gemeos(
    gemeos: dict[int, Gemeo],
    por_id: dict[int, Comentario],
    lado_de: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Contagens de um cruzamento, mais a lista de pares (só ids e números)."""
    niveis = Counter(gemeo.nivel for gemeo in gemeos.values())
    mesmo_video = sum(
        por_id[g.id_comentario].id_video == por_id[g.id_gemeo].id_video for g in gemeos.values()
    )
    curtos = sum(_curto(por_id[g.id_comentario]) for g in gemeos.values())
    resumo: dict[str, Any] = {
        "com_gemeo": len(gemeos),
        "exato": niveis.get(NIVEL_EXATO, 0),
        "quase": niveis.get(NIVEL_QUASE, 0),
        "gemeo_do_mesmo_video": mesmo_video,
        f"curtos_ate_{PALAVRAS_CURTO}_palavras": curtos,
    }
    resumo["pares"] = [
        {
            "id_comentario": gemeo.id_comentario,
            "id_gemeo": gemeo.id_gemeo,
            **({"lado_do_gemeo": lado_de[gemeo.id_gemeo]} if lado_de else {}),
            "nivel": gemeo.nivel,
            "similaridade": round(gemeo.similaridade, 4),
            "mesmo_video": por_id[gemeo.id_comentario].id_video == por_id[gemeo.id_gemeo].id_video,
        }
        for gemeo in sorted(gemeos.values(), key=lambda g: g.id_comentario)
    ]
    return resumo


def histograma_melhor_similaridade(
    consulta: list[Comentario], referencia: list[Comentario], largura: float = 0.05
) -> list[dict[str, Any]]:
    """Para cada comentário da consulta, a maior similaridade na referência, em faixas.

    É o que sustenta a escolha do limiar no TCC sem mostrar texto: onde a massa da
    distribuição está, e quantos pares ficam perto do corte.
    """
    gramas_referencia = [(c.id_comentario, ngramas(normalizar(c.texto_modelo))) for c in referencia]
    faixas = Counter()
    for comentario in consulta:
        gramas = ngramas(normalizar(comentario.texto_modelo))
        melhor = max(
            (
                jaccard(gramas, outro)
                for id_outro, outro in gramas_referencia
                if id_outro != comentario.id_comentario
            ),
            default=0.0,
        )
        faixas[min(int(melhor / largura), int(1 / largura) - 1)] += 1
    return [
        {
            "faixa": f"[{indice * largura:.2f}; {(indice + 1) * largura:.2f}"
            + ("]" if indice == int(1 / largura) - 1 else ")"),
            "comentarios": faixas.get(indice, 0),
        }
        for indice in range(int(1 / largura))
    ]


def mostrar_exemplos(
    titulo: str, gemeos: dict[int, Gemeo], por_id: dict[int, Comentario], quantos: int
) -> None:
    """Console só. Texto de terceiros não vai para arquivo versionado."""
    if not quantos:
        return
    for nivel in (NIVEL_EXATO, NIVEL_QUASE):
        do_nivel = [g for g in gemeos.values() if g.nivel == nivel]
        # Os mais longos primeiro: o par curto ("Parabéns" x "parabéns") é o caso
        # trivial, e o que se quer ver é o gêmeo que de fato parece cópia.
        do_nivel.sort(key=lambda g: (-len(por_id[g.id_comentario].texto), g.id_comentario))
        logger.info("")
        logger.info(
            "  %s - nivel %s (%d pares; %d exemplos)",
            titulo,
            nivel,
            len(do_nivel),
            min(quantos, len(do_nivel)),
        )
        for gemeo in do_nivel[:quantos]:
            a, b = por_id[gemeo.id_comentario], por_id[gemeo.id_gemeo]
            logger.info(
                "    %.2f  [%s | %s]  %r",
                gemeo.similaridade,
                a.rotulo_humano or a.rotulo_fraco,
                b.rotulo_fraco,
                a.texto[:100],
            )
            logger.info("          %s  %r", " " * 17, b.texto[:100])


def _resumir_avaliacao(avaliacao: Avaliacao) -> dict[str, Any]:
    metricas = avaliacao.metricas
    return {
        "n": metricas.total,
        "f1_macro": metricas.f1_macro,
        "ic95_f1_macro": avaliacao.intervalos.get("macro"),
        "acuracia": metricas.acuracia,
        "f1_por_classe": {classe: m.f1 for classe, m in metricas.por_classe.items()},
        "kappa_cohen": avaliacao.kappa,
    }


def metricas_por_grupo(
    metodos: list[tuple[str, str, dict[int, str]]],
    gabarito: dict[int, str],
    grupos: dict[str, set[int]],
    reamostragens: int,
) -> dict[str, dict[str, Any]]:
    """Cada método em cada grupo, com o mesmo `avaliar_metodo` do Capítulo 5."""
    resultado: dict[str, dict[str, Any]] = {}
    for nome, origem, previsoes in metodos:
        resultado[nome] = {}
        for grupo, ids in grupos.items():
            sub = {i: gabarito[i] for i in ids if i in gabarito}
            if not sub:
                resultado[nome][grupo] = None
                continue
            resultado[nome][grupo] = _resumir_avaliacao(
                avaliar_metodo(nome, origem, sub, previsoes, reamostragens)
            )
    return resultado


def repeticao_do_rotulo(
    gemeos_no_treino: dict[int, Gemeo],
    por_id: dict[int, Comentario],
    metodos: list[tuple[str, str, dict[int, str]]],
) -> dict[str, Any]:
    """Com gêmeo no TREINO: quantas vezes o método devolve o rótulo fraco do gêmeo.

    O BERTimbau treinou com aquele rótulo. Se ele repete o rótulo do gêmeo mais vezes
    do que o próprio gabarito concorda com ele, é sinal de memória, não de leitura.
    """
    if not gemeos_no_treino:
        return {"n": 0}
    rotulo_do_gemeo = {
        g.id_comentario: por_id[g.id_gemeo].rotulo_fraco for g in gemeos_no_treino.values()
    }
    n = len(rotulo_do_gemeo)
    saida: dict[str, Any] = {
        "n": n,
        "gabarito_igual_ao_rotulo_fraco_do_gemeo": sum(
            por_id[i].rotulo_humano == rotulo for i, rotulo in rotulo_do_gemeo.items()
        ),
    }
    for nome, _, previsoes in metodos:
        saida[f"{nome}_igual_ao_rotulo_fraco_do_gemeo"] = sum(
            previsoes.get(i) == rotulo for i, rotulo in rotulo_do_gemeo.items()
        )
    return saida


def gravar_tabela(resultado: dict[str, Any], caminho: Path) -> None:
    """Markdown com o que vai para o TCC: contagens e métricas por grupo."""
    a = resultado["teste_x_treino_validacao"]
    b = resultado["validacao_x_treino"]
    c = resultado["dentro_do_treino"]
    linhas = [
        "# Vazamento entre treino, validacao e teste\n",
        f"\nCriterio: `ml/avaliacao/gemeos.py` (exato = texto normalizado identico; quase = "
        f"Jaccard de trigramas >= {resultado['criterio']['limiar_quase']}).\n",
        "\n## Contagens\n\n",
        "| cruzamento | universo | com gemeo | exato | quase | do mesmo video "
        f"| curtos (<= {PALAVRAS_CURTO} palavras) |\n",
        "|---|---|---|---|---|---|---|\n",
    ]
    for rotulo, bloco, universo in (
        ("(a) teste x treino+validacao", a, resultado["conjuntos"]["teste"]),
        ("(b) validacao x treino", b, resultado["conjuntos"]["validacao"]),
        ("(c) treino x treino", c, resultado["conjuntos"]["treino"]),
    ):
        linhas.append(
            f"| {rotulo} | {universo} | {bloco['com_gemeo']} | {bloco['exato']} "
            f"| {bloco['quase']} | {bloco['gemeo_do_mesmo_video']} "
            f"| {bloco[f'curtos_ate_{PALAVRAS_CURTO}_palavras']} |\n"
        )
    linhas.append(
        f"\nNo (a): {a['com_gemeo_no_treino']} com gemeo no treino, "
        f"{a['com_gemeo_na_validacao']} com gemeo na validacao.\n"
    )

    linhas.append("\n## Metricas no teste, com e sem gemeo (IC 95%, bootstrap)\n\n")
    linhas.append(
        "| metodo | grupo | n | F1 macro | IC 95% | acuracia |\n|---|---|---|---|---|---|\n"
    )
    for metodo, grupos in resultado["metricas_teste"].items():
        for grupo, valores in grupos.items():
            if valores is None:
                linhas.append(f"| {metodo} | {grupo} | 0 | - | - | - |\n")
                continue
            ic = valores["ic95_f1_macro"]
            faixa = f"[{ic[0]:.3f}; {ic[1]:.3f}]" if ic else "-"
            linhas.append(
                f"| {metodo} | {grupo} | {valores['n']} | {valores['f1_macro']:.3f} | {faixa} "
                f"| {valores['acuracia']:.3f} |\n"
            )

    repeticao = resultado["repeticao_do_rotulo_do_gemeo_no_treino"]
    if repeticao.get("n"):
        linhas.append(
            f"\n## Com gemeo no treino (n = {repeticao['n']}): "
            "quem repete o rotulo fraco do gemeo\n\n"
        )
        linhas.append("| quem | concorda com o rotulo fraco do gemeo |\n|---|---|\n")
        for chave, valor in repeticao.items():
            if chave == "n":
                continue
            linhas.append(
                f"| {chave.removesuffix('_igual_ao_rotulo_fraco_do_gemeo')} | {valor} |\n"
            )

    caminho.write_text("".join(linhas), encoding="utf-8")
    logger.info("tabela -> %s", caminho)


def executar(argumentos: argparse.Namespace) -> dict[str, Any]:
    comentarios = asyncio.run(carregar(argumentos.id_execucao))
    treino, validacao, teste = separar(comentarios)
    por_id = {c.id_comentario: c for c in comentarios}
    limiar = argumentos.limiar
    logger.info(
        "treino %d | validacao %d | teste %d | limiar quase %.2f",
        len(treino),
        len(validacao),
        len(teste),
        limiar,
    )

    lado_de = {c.id_comentario: "treino" for c in treino} | {
        c.id_comentario: "validacao" for c in validacao
    }

    # (a) teste x treino+validacao
    teste_x_pool = buscar_gemeos(_pares(teste), _pares(treino + validacao), limiar)
    teste_x_treino = buscar_gemeos(_pares(teste), _pares(treino), limiar)
    teste_x_validacao = buscar_gemeos(_pares(teste), _pares(validacao), limiar)
    bloco_a = resumir_gemeos(teste_x_pool, por_id, lado_de)
    bloco_a["com_gemeo_no_treino"] = len(teste_x_treino)
    bloco_a["com_gemeo_na_validacao"] = len(teste_x_validacao)
    bloco_a["gabarito_igual_ao_rotulo_fraco_do_gemeo"] = sum(
        por_id[g.id_comentario].rotulo_humano == por_id[g.id_gemeo].rotulo_fraco
        for g in teste_x_pool.values()
    )

    # (b) validacao x treino
    validacao_x_treino = buscar_gemeos(_pares(validacao), _pares(treino), limiar)
    bloco_b = resumir_gemeos(validacao_x_treino, por_id)
    bloco_b["rotulo_fraco_igual_ao_do_gemeo"] = sum(
        por_id[g.id_comentario].rotulo_fraco == por_id[g.id_gemeo].rotulo_fraco
        for g in validacao_x_treino.values()
    )

    # (c) dentro do treino
    dentro = buscar_gemeos(_pares(treino), _pares(treino), limiar)
    bloco_c = resumir_gemeos(dentro, por_id)
    grupos_exatos = Counter(
        normalizar(por_id[i].texto_modelo) for i, g in dentro.items() if g.nivel == NIVEL_EXATO
    )
    bloco_c["grupos_de_texto_exato"] = len(grupos_exatos)
    bloco_c["rotulo_fraco_igual_ao_do_gemeo"] = sum(
        por_id[g.id_comentario].rotulo_fraco == por_id[g.id_gemeo].rotulo_fraco
        for g in dentro.values()
    )

    if argumentos.exemplos:
        logger.info("")
        logger.info("EXEMPLOS (so no console; [rotulo do primeiro | rotulo fraco do gemeo])")
        mostrar_exemplos("(a) teste x treino+validacao", teste_x_pool, por_id, argumentos.exemplos)
        mostrar_exemplos("(b) validacao x treino", validacao_x_treino, por_id, argumentos.exemplos)
        mostrar_exemplos("(c) treino x treino", dentro, por_id, argumentos.exemplos)

    # Metricas no teste, com e sem gemeo
    gabarito = {c.id_comentario: c.rotulo_humano for c in teste if c.rotulo_humano}
    metodos: list[tuple[str, str, dict[int, str]]] = []
    problemas = []
    for especificacao in argumentos.previsoes:
        nome, caminho = especificacao.split("=", 1)
        previsoes, encontrados = ler_csv(Path(caminho), nome)
        problemas += encontrados + validar_cobertura(gabarito, previsoes, nome)
        metodos.append((nome, f"csv: {Path(caminho).name}", previsoes))
    metodos.append(
        (
            METODO_GEMINI,
            "banco: exemplos_treinamento.rotulo_fraco",
            {c.id_comentario: c.rotulo_fraco for c in teste if c.rotulo_fraco},
        )
    )
    if problemas:
        for problema in problemas[:20]:
            logger.error("  %s", problema)
        raise SystemExit(f"VALIDACAO FALHOU - {len(problemas)} problema(s) nas previsoes")

    ids_teste = set(gabarito)
    com = set(teste_x_pool) & ids_teste
    grupos = {
        "todos": ids_teste,
        "com_gemeo": com,
        "sem_gemeo": ids_teste - com,
        "com_gemeo_exato": {i for i in com if teste_x_pool[i].nivel == NIVEL_EXATO},
        "com_gemeo_no_treino": set(teste_x_treino) & ids_teste,
    }
    metricas = metricas_por_grupo(metodos, gabarito, grupos, argumentos.reamostragens)

    return {
        "data_utc": datetime.now(UTC).isoformat(),
        "id_execucao": argumentos.id_execucao,
        "aviso": "so contagens, ids e metricas: nenhum texto de comentario",
        "criterio": {
            "modulo": "ml/avaliacao/gemeos.py",
            "texto_comparado": "texto_modelo (preparar_texto), o que o BERTimbau le",
            "normalizacao": "minusculas, sem acento, sem pontuacao, letra repetida reduzida a uma",
            "exato": "texto normalizado identico",
            "quase": f"nao exato e Jaccard de {TAMANHO_NGRAMA}-gramas de caractere >= limiar",
            "limiar_quase": limiar,
            "curto": f"ate {PALAVRAS_CURTO} palavras normalizadas",
        },
        "particao": "a do treino da rodada 1: dividir_estratificado, 85/15, semente 42",
        "conjuntos": {"treino": len(treino), "validacao": len(validacao), "teste": len(teste)},
        "histograma_melhor_similaridade_teste_x_treino_validacao": histograma_melhor_similaridade(
            teste, treino + validacao
        ),
        "teste_x_treino_validacao": bloco_a,
        "validacao_x_treino": bloco_b,
        "dentro_do_treino": bloco_c,
        "bootstrap": {
            "reamostragens": argumentos.reamostragens,
            "confianca": CONFIANCA,
            "semente": SEMENTE,
            "metodo": "percentil",
        },
        "grupos_do_teste": {grupo: len(ids) for grupo, ids in grupos.items()},
        "metricas_teste": metricas,
        "repeticao_do_rotulo_do_gemeo_no_treino": repeticao_do_rotulo(
            {i: g for i, g in teste_x_treino.items() if i in ids_teste}, por_id, metodos
        ),
    }


def relatar(resultado: dict[str, Any]) -> None:
    logger.info("")
    logger.info("=" * 78)
    logger.info("VAZAMENTO")
    logger.info("=" * 78)
    for chave in ("teste_x_treino_validacao", "validacao_x_treino", "dentro_do_treino"):
        bloco = {k: v for k, v in resultado[chave].items() if k != "pares"}
        logger.info("  %s: %s", chave, bloco)
    logger.info("")
    logger.info("%-24s %-22s %5s %9s %20s", "metodo", "grupo", "n", "F1 macro", "IC 95%")
    for metodo, grupos in resultado["metricas_teste"].items():
        for grupo, valores in grupos.items():
            if valores is None:
                continue
            ic = valores["ic95_f1_macro"]
            logger.info(
                "%-24s %-22s %5d %9.4f %20s",
                metodo,
                grupo,
                valores["n"],
                valores["f1_macro"],
                f"[{ic[0]:.4f}; {ic[1]:.4f}]" if ic else "-",
            )
    logger.info("")
    logger.info(
        "repeticao do rotulo do gemeo: %s", resultado["repeticao_do_rotulo_do_gemeo_no_treino"]
    )
    logger.info("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument(
        "--previsoes",
        action="append",
        default=None,
        metavar="nome=arquivo.csv",
        help="metodo a recalcular com e sem gemeo (padrao: lexico e bertimbau de ml/dados/)",
    )
    parser.add_argument("--limiar", type=float, default=LIMIAR_QUASE)
    parser.add_argument("--exemplos", type=int, default=5, help="pares por nivel, so no console")
    parser.add_argument("--reamostragens", type=int, default=REAMOSTRAGENS)
    parser.add_argument("--saida", type=Path, default=DIRETORIO_SAIDA)
    argumentos = parser.parse_args()
    if argumentos.previsoes is None:
        argumentos.previsoes = list(PREVISOES_PADRAO)

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    resultado = executar(argumentos)
    relatar(resultado)

    argumentos.saida.mkdir(parents=True, exist_ok=True)
    caminho = argumentos.saida / "resultado_vazamento.json"
    caminho.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("relatorio -> %s", caminho)
    gravar_tabela(resultado, argumentos.saida / "tabela_vazamento.md")


if __name__ == "__main__":
    main()
