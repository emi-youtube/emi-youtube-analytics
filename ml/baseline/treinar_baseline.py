"""Baseline clássico: TF-IDF + regressão logística, nas mesmas condições do BERTimbau.

O Capítulo 5 compara o BERTimbau com um piso léxico (SentiLex) e com a própria Gemini.
Falta o degrau do meio: um classificador supervisionado clássico, treinado com os
MESMOS dados. Sem ele, a banca não tem como separar "o BERTimbau é bom" de "qualquer
modelo supervisionado com 1.870 rótulos fracos chegaria lá".

**Mesmas condições, ponto a ponto:**

| | BERTimbau (rodada 1) | este baseline |
|---|---|---|
| exemplos | 2.200 de `split IS NULL`, `rotulo_fraco` | os mesmos (`carregar_exemplos`) |
| partição | 1.870 / 330, `dividir_estratificado`, semente 42 | a mesma função, a mesma semente |
| texto | `preparar_texto` | o mesmo `texto_modelo` |
| desbalanceamento | peso `N / (k * n_j)` | `class_weight='balanced'` (a mesma fórmula) |
| escolha de hiperparâmetro | F1 macro de validação | F1 macro de validação |
| teste | 334, `rotulo_humano`, uma vez | o mesmo, uma vez, o mesmo código de `ml/avaliacao/` |

**Duas etapas, separadas de propósito** — a mesma separação de `treinar.py` e
`prever_teste.py`:

- `selecionar` treina a grade, escolhe pela validação, roda a validação por grupo de
  vídeos e grava `ml/baseline/saida/busca_baseline.json`. **Não lê o teste.**
- `avaliar-teste` lê a configuração escolhida DAQUELE arquivo (não escolhe de novo),
  treina no treino, classifica os 334 e avalia. Recusa rodar uma segunda vez se as
  previsões já existirem, a menos de `--refazer` — o teste é olhado uma vez.

Uso:
    python -m ml.baseline.treinar_baseline selecionar --id-execucao 4
    python -m ml.baseline.treinar_baseline avaliar-teste --id-execucao 4
"""

import argparse
import asyncio
import csv
import json
import logging
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.pipeline import FeatureUnion, Pipeline

from ml.avaliacao.avaliar import (
    METODO_GEMINI,
    avaliar_metodo,
    gravar_relatorio,
    gravar_tabelas,
    ler_csv,
    ler_do_banco,
    relatar,
    validar_cobertura,
)
from ml.avaliacao.metricas import (
    CONFIANCA,
    REAMOSTRAGENS,
    avaliar_previsoes,
    intervalo_bootstrap,
    intervalo_bootstrap_pareado,
)
from ml.config import CLASSES, DIRETORIO_DADOS, DIRETORIO_ML, SEMENTE, dsn_postgres
from ml.treino.dados import (
    Exemplo,
    carregar_exemplos,
    carregar_teste,
    distribuicao,
    dividir_estratificado,
)

logger = logging.getLogger("baseline")

DIRETORIO_SAIDA = DIRETORIO_ML / "baseline" / "saida"
ARQUIVO_BUSCA = DIRETORIO_SAIDA / "busca_baseline.json"
ARQUIVO_PREVISOES = DIRETORIO_DADOS / "previsoes_baseline.csv"
NOME_METODO = "tfidf_logreg"

# A grade, pequena: 3 x 2 x 2 = 12 configurações. C em escala logarítmica de década
# em década (o efeito de C é multiplicativo), n-gramas de palavra com e sem bigrama, e
# n-gramas de caractere ligados ou não. Caractere é o que dá ao modelo linear alguma
# robustez a grafia ("musica" x "música", "vamooo") sem pré-processamento extra.
GRADE_C = (0.1, 1.0, 10.0)
GRADE_NGRAMAS_PALAVRA = ((1, 1), (1, 2))
GRADE_CARACTERE = (False, True)
NGRAMAS_CARACTERE = (2, 5)

DOBRAS = 5


@dataclass(frozen=True)
class Configuracao:
    c: float
    ngramas_palavra: tuple[int, int]
    caractere: bool

    def descrever(self) -> str:
        carac = f" + char_wb{NGRAMAS_CARACTERE}" if self.caractere else ""
        return f"C={self.c:g} palavra{self.ngramas_palavra}{carac}"


def montar_pipeline(configuracao: Configuracao) -> Pipeline:
    """TF-IDF (palavra, e caractere se pedido) seguido da regressão logística.

    `token_pattern` aceita palavra de uma letra: o padrão do scikit-learn descarta "q",
    "k", "s" e "n" — e "n" (não) muda o sentimento da frase. `sublinear_tf` amortece a
    repetição ("lindo lindo lindo" não vale três vezes "lindo"). A semente vai na
    regressão para o resultado não depender da máquina.
    """
    partes: list[tuple[str, TfidfVectorizer]] = [
        (
            "palavra",
            TfidfVectorizer(
                lowercase=True,
                ngram_range=configuracao.ngramas_palavra,
                token_pattern=r"(?u)\b\w+\b",
                sublinear_tf=True,
            ),
        )
    ]
    if configuracao.caractere:
        partes.append(
            (
                "caractere",
                TfidfVectorizer(
                    lowercase=True,
                    analyzer="char_wb",
                    ngram_range=NGRAMAS_CARACTERE,
                    sublinear_tf=True,
                ),
            )
        )
    return Pipeline(
        [
            ("tfidf", FeatureUnion(partes)),
            (
                "logreg",
                LogisticRegression(
                    C=configuracao.c,
                    class_weight="balanced",
                    max_iter=5000,
                    random_state=SEMENTE,
                ),
            ),
        ]
    )


def grade() -> list[Configuracao]:
    """Da mais simples para a mais complexa: em empate de F1, vence a primeira."""
    return [
        Configuracao(c, ngramas, caractere)
        for caractere in GRADE_CARACTERE
        for ngramas in GRADE_NGRAMAS_PALAVRA
        for c in GRADE_C
    ]


def _textos(exemplos: list[Exemplo]) -> list[str]:
    return [exemplo.texto_modelo for exemplo in exemplos]


def _rotulos(exemplos: list[Exemplo]) -> list[str]:
    return [exemplo.rotulo for exemplo in exemplos]


def f1_macro(verdadeiros: list[str], previstos: list[str]) -> float:
    """O F1 macro do projeto (denominador 3), da mesma função do Capítulo 5."""
    return avaliar_previsoes(verdadeiros, previstos, CLASSES).f1_macro


async def videos_dos_comentarios(id_execucao: int) -> dict[int, int]:
    """id_comentario -> id_video, para a validação por grupo."""
    conexao = await asyncpg.connect(dsn_postgres())
    try:
        registros = await conexao.fetch(
            """
            SELECT c.id_comentario, c.id_video
            FROM comentarios c JOIN videos v ON v.id_video = c.id_video
            WHERE v.id_execucao = $1
            """,
            id_execucao,
        )
    finally:
        await conexao.close()
    return {registro["id_comentario"]: registro["id_video"] for registro in registros}


def buscar(treino: list[Exemplo], validacao: list[Exemplo]) -> list[dict[str, Any]]:
    """Treina cada configuração no treino e mede o F1 macro na validação."""
    resultados = []
    verdadeiros = _rotulos(validacao)
    for configuracao in grade():
        pipeline = montar_pipeline(configuracao).fit(_textos(treino), _rotulos(treino))
        previstos = list(pipeline.predict(_textos(validacao)))
        metricas = avaliar_previsoes(verdadeiros, previstos, CLASSES)
        resultados.append(
            {
                "c": configuracao.c,
                "ngramas_palavra": list(configuracao.ngramas_palavra),
                "caractere": configuracao.caractere,
                "atributos": len(pipeline.named_steps["tfidf"].get_feature_names_out()),
                "f1_macro": metricas.f1_macro,
                "acuracia": metricas.acuracia,
                "f1_por_classe": {classe: m.f1 for classe, m in metricas.por_classe.items()},
            }
        )
        logger.info(
            "  %-34s val F1 macro=%.4f  acuracia=%.4f",
            configuracao.descrever(),
            metricas.f1_macro,
            metricas.acuracia,
        )
    return resultados


def validar_por_grupo(
    exemplos: list[Exemplo], videos: dict[int, int], configuracao: Configuracao
) -> dict[str, Any]:
    """Partição aleatória x partição por vídeo, ambas em 5 dobras, contra o rótulo fraco.

    A pergunta é quanto o desempenho cai num vídeo que o modelo nunca viu — que é a
    situação real da PME: a campanha dela não estava no corpus. Na partição aleatória
    (estratificada), comentários do mesmo vídeo caem dos dois lados, e o modelo pode
    acertar por reconhecer o assunto do vídeo ("nivus", "whopper"). Na `GroupKFold`,
    cada vídeo fica inteiro numa dobra só.

    Mesmos 2.200, mesma configuração, mesmo número de dobras: a diferença entre as duas
    é a estimativa da queda. O rótulo é o fraco (Gemini) — mede imitação da Gemini em
    vídeo inédito, não acerto contra humano; a QUEDA é que interessa.

    Além da média ± desvio por dobra, sai o F1 do conjunto inteiro das previsões fora
    da dobra (cada comentário previsto uma vez, pelo modelo que não o viu), com IC por
    bootstrap. A média das dobras com 14 vídeos desiguais oscila muito; o agregado é
    mais estável.
    """
    textos = _textos(exemplos)
    rotulos = _rotulos(exemplos)
    grupos = [videos[exemplo.id_comentario] for exemplo in exemplos]

    esquemas = {
        "aleatoria_estratificada": StratifiedKFold(
            n_splits=DOBRAS, shuffle=True, random_state=SEMENTE
        ).split(textos, rotulos),
        "por_video_groupkfold": GroupKFold(n_splits=DOBRAS).split(textos, rotulos, grupos),
    }
    saida: dict[str, Any] = {}
    for nome, dobras in esquemas.items():
        fora_da_dobra: dict[int, str] = {}
        por_dobra = []
        for numero, (indices_treino, indices_teste) in enumerate(dobras, start=1):
            pipeline = montar_pipeline(configuracao).fit(
                [textos[i] for i in indices_treino], [rotulos[i] for i in indices_treino]
            )
            previstos = list(pipeline.predict([textos[i] for i in indices_teste]))
            for posicao, previsto in zip(indices_teste, previstos, strict=True):
                fora_da_dobra[posicao] = previsto
            por_dobra.append(
                {
                    "dobra": numero,
                    "n": len(indices_teste),
                    "videos": sorted({grupos[i] for i in indices_teste}),
                    "f1_macro": f1_macro([rotulos[i] for i in indices_teste], previstos),
                }
            )
        ordem = sorted(fora_da_dobra)
        verdadeiros = [rotulos[i] for i in ordem]
        previstos = [fora_da_dobra[i] for i in ordem]
        valores = [dobra["f1_macro"] for dobra in por_dobra]
        saida[nome] = {
            "f1_macro_media_das_dobras": statistics.mean(valores),
            "f1_macro_desvio_das_dobras": statistics.stdev(valores),
            "f1_macro_fora_da_dobra": f1_macro(verdadeiros, previstos),
            "ic95_f1_macro_fora_da_dobra": intervalo_bootstrap(verdadeiros, previstos, CLASSES).get(
                "macro"
            ),
            "dobras": por_dobra,
        }
        logger.info(
            "  %-26s F1 macro dobras %.4f +- %.4f | fora da dobra %.4f",
            nome,
            saida[nome]["f1_macro_media_das_dobras"],
            saida[nome]["f1_macro_desvio_das_dobras"],
            saida[nome]["f1_macro_fora_da_dobra"],
        )

    aleatoria = saida["aleatoria_estratificada"]
    por_video = saida["por_video_groupkfold"]
    saida["queda_estimada_em_video_inedito"] = {
        "media_das_dobras": aleatoria["f1_macro_media_das_dobras"]
        - por_video["f1_macro_media_das_dobras"],
        "fora_da_dobra": aleatoria["f1_macro_fora_da_dobra"] - por_video["f1_macro_fora_da_dobra"],
    }
    saida["dobras"] = DOBRAS
    saida["rotulo"] = "rotulo_fraco (Gemini) - mede a QUEDA, nao o acerto contra humano"
    return saida


def selecionar(argumentos: argparse.Namespace) -> None:
    exemplos = asyncio.run(carregar_exemplos(argumentos.id_execucao))
    particao = dividir_estratificado(exemplos)
    logger.info("treino %d | validacao %d", len(particao.treino), len(particao.validacao))

    logger.info("")
    logger.info("BUSCA - %d configuracoes, escolha pelo F1 macro de VALIDACAO", len(grade()))
    resultados = buscar(particao.treino, particao.validacao)
    # max() devolve o primeiro em caso de empate: a grade vai da mais simples para a
    # mais complexa, então o empate escolhe a mais simples.
    melhor = max(resultados, key=lambda resultado: resultado["f1_macro"])
    escolhida = Configuracao(melhor["c"], tuple(melhor["ngramas_palavra"]), melhor["caractere"])
    logger.info("escolhida pela validacao: %s", escolhida.descrever())

    logger.info("")
    logger.info("VALIDACAO POR GRUPO - %d dobras, os 2.200, rotulo fraco", DOBRAS)
    videos = asyncio.run(videos_dos_comentarios(argumentos.id_execucao))
    por_grupo = validar_por_grupo(particao.treino + particao.validacao, videos, escolhida)

    DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "aviso": (
            "metricas de VALIDACAO com rotulo fraco (Gemini): escolhem hiperparametro e "
            "estimam a queda em video inedito. NAO vao para o Capitulo 5 como acerto; o "
            "numero do capitulo sai de avaliar-teste, contra o rotulo_humano."
        ),
        "data_utc": datetime.now(UTC).isoformat(),
        "id_execucao": argumentos.id_execucao,
        "dados": {
            "fonte": "exemplos_treinamento.rotulo_fraco, split IS NULL",
            "treino": len(particao.treino),
            "validacao": len(particao.validacao),
            "distribuicao_treino": distribuicao(particao.treino),
            "distribuicao_validacao": distribuicao(particao.validacao),
            "particao": "dividir_estratificado, 85/15, semente 42 (a do treino oficial)",
            "texto": "texto_modelo (preparar_texto)",
        },
        "modelo": {
            "vetorizacao": "TF-IDF, sublinear_tf, palavra token (?u)\\b\\w+\\b"
            + f", caractere char_wb {list(NGRAMAS_CARACTERE)} quando ligado",
            "classificador": "LogisticRegression lbfgs, class_weight='balanced', max_iter 5000",
            "semente": SEMENTE,
        },
        "criterio": "F1 macro de validacao; empate -> configuracao mais simples",
        "escolhida": {**asdict(escolhida), "ngramas_palavra": list(escolhida.ngramas_palavra)},
        "grade": sorted(resultados, key=lambda resultado: -resultado["f1_macro"]),
        "validacao_por_grupo": por_grupo,
    }
    ARQUIVO_BUSCA.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("busca -> %s", ARQUIVO_BUSCA)


def avaliar_teste(argumentos: argparse.Namespace) -> None:
    if not ARQUIVO_BUSCA.exists():
        raise SystemExit(f"{ARQUIVO_BUSCA} nao existe: rode `selecionar` antes.")
    if ARQUIVO_PREVISOES.exists() and not argumentos.refazer:
        raise SystemExit(
            f"{ARQUIVO_PREVISOES} ja existe: o teste do baseline ja foi olhado. "
            "--refazer so para erro de operacao, e a repeticao vai para o README."
        )

    busca = json.loads(ARQUIVO_BUSCA.read_text(encoding="utf-8"))
    escolhida = Configuracao(
        busca["escolhida"]["c"],
        tuple(busca["escolhida"]["ngramas_palavra"]),
        busca["escolhida"]["caractere"],
    )
    logger.info("configuracao de %s: %s", ARQUIVO_BUSCA.name, escolhida.descrever())

    exemplos = asyncio.run(carregar_exemplos(argumentos.id_execucao))
    particao = dividir_estratificado(exemplos)
    pipeline = montar_pipeline(escolhida).fit(_textos(particao.treino), _rotulos(particao.treino))

    # As previsoes saem ANTES de qualquer rotulo do teste ser lido: carregar_teste nao
    # traz rotulo_humano nem rotulo_fraco.
    teste = asyncio.run(carregar_teste(argumentos.id_execucao))
    probabilidades = pipeline.predict_proba(_textos(teste))
    classes_modelo = list(pipeline.classes_)
    ARQUIVO_PREVISOES.parent.mkdir(parents=True, exist_ok=True)
    with ARQUIVO_PREVISOES.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(("id_comentario", "previsto", "confianca"))
        for exemplo, linha in zip(teste, probabilidades, strict=True):
            indice = int(linha.argmax())
            escritor.writerow(
                (exemplo.id_comentario, classes_modelo[indice], f"{linha[indice]:.4f}")
            )
    logger.info("previsoes -> %s (%d comentarios)", ARQUIVO_PREVISOES, len(teste))

    # Avaliacao: o mesmo codigo do Capitulo 5, com os quatro metodos lado a lado.
    do_banco = asyncio.run(ler_do_banco(argumentos.id_execucao, "rotulo_humano"))
    gabarito = {id_comentario: rotulo for id_comentario, rotulo in do_banco.items() if rotulo}
    excluidos = len(do_banco) - len(gabarito)
    fracos = asyncio.run(ler_do_banco(argumentos.id_execucao, "rotulo_fraco"))

    metodos = []
    problemas = []
    for nome, caminho in (
        ("lexico", argumentos.lexico),
        ("bertimbau", argumentos.bertimbau),
        (NOME_METODO, ARQUIVO_PREVISOES),
    ):
        previsoes, encontrados = ler_csv(caminho, nome)
        problemas += encontrados + validar_cobertura(gabarito, previsoes, nome)
        metodos.append((nome, f"csv: {caminho.name}", previsoes))
    metodos.append(
        (
            METODO_GEMINI,
            "banco: exemplos_treinamento.rotulo_fraco",
            {i: r for i, r in fracos.items() if r},
        )
    )
    if problemas:
        for problema in problemas[:20]:
            logger.error("  %s", problema)
        raise SystemExit(f"VALIDACAO FALHOU - {len(problemas)} problema(s)")

    avaliacoes = [
        avaliar_metodo(nome, origem, gabarito, previsoes, REAMOSTRAGENS)
        for nome, origem, previsoes in metodos
    ]
    relatar(avaliacoes, excluidos)
    saida = DIRETORIO_SAIDA / "avaliacao"
    gravar_tabelas(avaliacoes, saida)
    gravar_relatorio(
        avaliacoes,
        excluidos,
        f"banco: exemplos_treinamento.rotulo_humano (execucao {argumentos.id_execucao})",
        REAMOSTRAGENS,
        saida / "resultado_avaliacao.json",
    )
    from ml.avaliacao.graficos import gerar_figuras

    gerar_figuras(avaliacoes, saida / "figuras")

    # Diferenca pareada: BERTimbau (B) menos baseline (A), nos mesmos 334.
    ids = sorted(gabarito)
    previsoes_por_nome = {nome: previsoes for nome, _, previsoes in metodos}
    delta = intervalo_bootstrap_pareado(
        [gabarito[i] for i in ids],
        [previsoes_por_nome[NOME_METODO][i] for i in ids],
        [previsoes_por_nome["bertimbau"][i] for i in ids],
        CLASSES,
    )
    logger.info("")
    logger.info(
        "BERTimbau - %s: %+.4f  IC %.0f%% pareado [%+.4f; %+.4f]",
        NOME_METODO,
        delta.delta,
        100 * CONFIANCA,
        delta.ic[0],
        delta.ic[1],
    )
    comparacao = {
        "data_utc": datetime.now(UTC).isoformat(),
        "configuracao": {**asdict(escolhida), "ngramas_palavra": list(escolhida.ngramas_palavra)},
        "treinado_em": f"{len(particao.treino)} exemplos (treino da particao semente 42)",
        "total_avaliado": len(ids),
        "a": {"metodo": NOME_METODO, "f1_macro": delta.f1_macro_a},
        "b": {"metodo": "bertimbau", "f1_macro": delta.f1_macro_b},
        "delta_bertimbau_menos_baseline": delta.delta,
        "ic95_delta_pareado": list(delta.ic),
        "bootstrap": {"reamostragens": delta.reamostragens, "metodo": "percentil pareado"},
    }
    caminho = DIRETORIO_SAIDA / "comparacao_bertimbau_baseline.json"
    caminho.write_text(json.dumps(comparacao, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("comparacao -> %s", caminho)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    etapas = parser.add_subparsers(dest="etapa", required=True)

    seletor = etapas.add_parser("selecionar", help="grade + validacao por grupo; nao le o teste")
    seletor.add_argument("--id-execucao", type=int, required=True)

    avaliador = etapas.add_parser("avaliar-teste", help="treina a escolhida e avalia no teste")
    avaliador.add_argument("--id-execucao", type=int, required=True)
    avaliador.add_argument("--lexico", type=Path, default=DIRETORIO_DADOS / "previsoes_lexico.csv")
    avaliador.add_argument(
        "--bertimbau", type=Path, default=DIRETORIO_DADOS / "previsoes_bertimbau.csv"
    )
    avaliador.add_argument("--refazer", action="store_true")

    argumentos = parser.parse_args()
    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    if argumentos.etapa == "selecionar":
        selecionar(argumentos)
    else:
        avaliar_teste(argumentos)


if __name__ == "__main__":
    main()
