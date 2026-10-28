"""Sensibilidade das métricas do Capítulo 5 a três escolhas do protocolo.

O teste humano (334 comentários) é medido como amostra simples. Três escolhas do
protocolo podem mudar a leitura, e esta análise mede cada uma, sem trocar o número
publicado:

1. **Estratos do sorteio.** A amostra foi sorteada estratificada pelo rótulo fraco,
   cerca de um terço por classe, enquanto o corpus tem outra proporção. Ponderar cada
   comentário pelo peso do seu estrato (N do estrato no corpus / n do estrato na
   amostra) estima o que o método faria sobre o corpus inteiro: a acurácia e a
   precisão por classe dependem da proporção das classes; o F1 macro, menos.
2. **Comentários do mesmo vídeo se parecem.** O intervalo publicado sorteia
   comentários; aqui o bootstrap sorteia VÍDEOS inteiros (os comentários de um vídeo
   entram ou saem juntos), o que dá a largura honesta quando os vídeos são poucos.
3. **Filtro de idioma.** O gabarito foi montado antes do filtro de idioma da coleta;
   aqui as métricas são refeitas sem os comentários que o filtro descartaria.

Entradas, nenhuma com texto de comentário:

- `--exemplos`: CSV exportado do banco (consulta Q7 de `consultas_producao_emi.sql`),
  com `id_comentario, id_video, rotulo_fraco, rotulo_humano, split` de TODO o corpus;
- `--previsoes nome=arquivo.csv`, uma por método (`id_comentario, previsto`); a Gemini
  entra sozinha, com o rótulo fraco como previsão;
- `--descartados-idioma`: CSV com a coluna `id_comentario` dos comentários de teste que
  o filtro de idioma descartaria (`ml/avaliacao/saida_sensibilidade/descartados_idioma.csv`).

    python -m ml.avaliacao.sensibilidade --exemplos exemplos.csv \\
        --previsoes lexico=ml/dados/previsoes_lexico.csv \\
        --previsoes tfidf_logreg=ml/dados/previsoes_baseline.csv \\
        --previsoes bertimbau=ml/dados/previsoes_bertimbau.csv
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from ml.avaliacao.avaliar import ler_csv
from ml.avaliacao.metricas import CONFIANCA, REAMOSTRAGENS, SEMENTE, avaliar_previsoes, percentil
from ml.concordancia.kappa import kappa_cohen
from ml.config import CLASSES, DIRETORIO_ML

SAIDA_PADRAO = DIRETORIO_ML / "avaliacao" / "saida_sensibilidade"
GEMINI = "gemini (rotulo_fraco)"

Matriz = dict[str, dict[str, float]]


def matriz_ponderada(
    verdadeiros: Sequence[str], previstos: Sequence[str], pesos: Sequence[float]
) -> Matriz:
    matriz: Matriz = {v: dict.fromkeys(CLASSES, 0.0) for v in CLASSES}
    for verdadeiro, previsto, peso in zip(verdadeiros, previstos, pesos, strict=True):
        matriz[verdadeiro][previsto] += peso
    return matriz


def metricas_da_matriz(matriz: Matriz) -> dict[str, object]:
    """Acurácia, P/R/F1 por classe, F1 macro (denominador 3) e kappa de uma matriz com pesos."""
    total = sum(sum(linha.values()) for linha in matriz.values())
    por_classe = {}
    for classe in CLASSES:
        vp = matriz[classe][classe]
        fn = sum(matriz[classe].values()) - vp
        fp = sum(matriz[outra][classe] for outra in CLASSES) - vp
        precisao = vp / (vp + fp) if vp + fp else 0.0
        revocacao = vp / (vp + fn) if vp + fn else 0.0
        f1 = 2 * precisao * revocacao / (precisao + revocacao) if precisao + revocacao else 0.0
        por_classe[classe] = {"precisao": precisao, "revocacao": revocacao, "f1": f1}
    acerto = sum(matriz[c][c] for c in CLASSES) / total
    esperado = sum(
        (sum(matriz[c].values()) / total) * (sum(matriz[o][c] for o in CLASSES) / total)
        for c in CLASSES
    )
    return {
        "acuracia": acerto,
        "f1_macro": sum(m["f1"] for m in por_classe.values()) / len(CLASSES),
        "kappa_cohen": (acerto - esperado) / (1 - esperado) if esperado < 1 else None,
        "por_classe": por_classe,
        "distribuicao_gabarito": {c: sum(matriz[c].values()) / total for c in CLASSES},
        "distribuicao_prevista": {c: sum(matriz[o][c] for o in CLASSES) / total for c in CLASSES},
    }


def _intervalo(valores: list[float]) -> list[float]:
    cauda = (1 - CONFIANCA) / 2
    return [percentil(valores, cauda), percentil(valores, 1 - cauda)]


def ponderado_pelos_estratos(
    teste: list[dict[str, str]],
    previstos: dict[int, str],
    populacao: Counter,
    reamostragens: int = REAMOSTRAGENS,
    semente: int = SEMENTE,
) -> dict[str, object]:
    """Pós-estratificação pelo rótulo fraco, com bootstrap estratificado para o IC."""
    amostra = Counter(t["rotulo_fraco"] for t in teste)
    peso = {s: populacao[s] / amostra[s] for s in amostra}
    verdadeiros = [t["rotulo_humano"] for t in teste]
    preditos = [previstos[int(t["id_comentario"])] for t in teste]
    pesos = [peso[t["rotulo_fraco"]] for t in teste]
    resultado = metricas_da_matriz(matriz_ponderada(verdadeiros, preditos, pesos))

    por_estrato: dict[str, list[int]] = defaultdict(list)
    for posicao, t in enumerate(teste):
        por_estrato[t["rotulo_fraco"]].append(posicao)
    sorteio = random.Random(semente)
    f1s, acuracias = [], []
    for _ in range(reamostragens):
        posicoes = [
            sorteio.choice(membros) for membros in por_estrato.values() for _ in range(len(membros))
        ]
        m = metricas_da_matriz(
            matriz_ponderada(
                [verdadeiros[p] for p in posicoes],
                [preditos[p] for p in posicoes],
                [pesos[p] for p in posicoes],
            )
        )
        f1s.append(m["f1_macro"])
        acuracias.append(m["acuracia"])
    resultado["ic95_f1_macro"] = _intervalo(f1s)
    resultado["ic95_acuracia"] = _intervalo(acuracias)
    resultado["peso_por_estrato"] = peso
    return resultado


def bootstrap_por_video(
    teste: list[dict[str, str]],
    metodos: dict[str, dict[int, str]],
    reamostragens: int = REAMOSTRAGENS,
    semente: int = SEMENTE,
) -> dict[str, object]:
    """IC do F1 macro sorteando vídeos inteiros; mesmo sorteio para todos os métodos."""
    por_video: dict[str, list[dict[str, str]]] = defaultdict(list)
    for t in teste:
        por_video[t["id_video"]].append(t)
    videos = sorted(por_video)
    sorteio = random.Random(semente)
    amostras: dict[str, list[float]] = {nome: [] for nome in metodos}
    diferencas: dict[str, list[float]] = defaultdict(list)
    for _ in range(reamostragens):
        escolhidos = [sorteio.choice(videos) for _ in videos]
        linhas = [t for v in escolhidos for t in por_video[v]]
        verdadeiros = [t["rotulo_humano"] for t in linhas]
        f1 = {}
        for nome, previstos in metodos.items():
            preditos = [previstos[int(t["id_comentario"])] for t in linhas]
            f1[nome] = avaliar_previsoes(verdadeiros, preditos, CLASSES).f1_macro
            amostras[nome].append(f1[nome])
        if "bertimbau" in f1 and "tfidf_logreg" in f1:
            diferencas["bertimbau - tfidf_logreg"].append(f1["bertimbau"] - f1["tfidf_logreg"])
    return {
        "videos": len(videos),
        "comentarios_por_video": {v: len(por_video[v]) for v in videos},
        "ic95_f1_macro": {nome: _intervalo(valores) for nome, valores in amostras.items()},
        "ic95_diferenca_pareada": {nome: _intervalo(v) for nome, v in diferencas.items()},
    }


def sem_descartados(
    teste: list[dict[str, str]], metodos: dict[str, dict[int, str]], descartados: set[int]
) -> dict[str, object]:
    ficam = [t for t in teste if int(t["id_comentario"]) not in descartados]
    verdadeiros = [t["rotulo_humano"] for t in ficam]
    resultado: dict[str, object] = {"n": len(ficam), "descartados": len(teste) - len(ficam)}
    for nome, previstos in metodos.items():
        preditos = [previstos[int(t["id_comentario"])] for t in ficam]
        m = avaliar_previsoes(verdadeiros, preditos, CLASSES)
        resultado[nome] = {
            "f1_macro": m.f1_macro,
            "acuracia": m.acuracia,
            "kappa_cohen": kappa_cohen(verdadeiros, preditos),
        }
    return resultado


def ler_exemplos(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    faltam = {"id_comentario", "id_video", "rotulo_fraco", "rotulo_humano", "split"} - set(
        linhas[0] if linhas else {}
    )
    if faltam:
        raise SystemExit(f"{caminho}: faltam as colunas {sorted(faltam)}")
    return linhas


def analisar(
    exemplos: list[dict[str, str]],
    previsoes: dict[str, dict[int, str]],
    descartados: set[int],
    reamostragens: int = REAMOSTRAGENS,
) -> dict[str, object]:
    teste = [e for e in exemplos if e["split"] == "teste" and e["rotulo_humano"]]
    if not teste:
        raise SystemExit("nenhum exemplo de teste com rotulo_humano no CSV")
    populacao = Counter(e["rotulo_fraco"] for e in exemplos if e["rotulo_fraco"])
    metodos = dict(previsoes)
    metodos[GEMINI] = {int(t["id_comentario"]): t["rotulo_fraco"] for t in teste}
    for nome, previstos in metodos.items():
        faltando = [t["id_comentario"] for t in teste if int(t["id_comentario"]) not in previstos]
        if faltando:
            raise SystemExit(f"{nome}: sem previsão para {len(faltando)} comentários de teste")

    verdadeiros = [t["rotulo_humano"] for t in teste]
    publicado = {}
    for nome, previstos in metodos.items():
        preditos = [previstos[int(t["id_comentario"])] for t in teste]
        m = avaliar_previsoes(verdadeiros, preditos, CLASSES)
        publicado[nome] = {
            "f1_macro": m.f1_macro,
            "acuracia": m.acuracia,
            "kappa_cohen": kappa_cohen(verdadeiros, preditos),
        }

    return {
        "teste": len(teste),
        "corpus": sum(populacao.values()),
        "populacao_por_rotulo_fraco": dict(populacao),
        "amostra_por_rotulo_fraco": dict(Counter(t["rotulo_fraco"] for t in teste)),
        "como_publicado": publicado,
        "ponderado_pelos_estratos": {
            nome: ponderado_pelos_estratos(teste, previstos, populacao, reamostragens)
            for nome, previstos in metodos.items()
        },
        "bootstrap_por_video": bootstrap_por_video(teste, metodos, reamostragens),
        "sem_filtro_de_idioma": sem_descartados(teste, metodos, descartados),
    }


def tabela_markdown(resultado: dict[str, object]) -> str:
    publicado = resultado["como_publicado"]
    ponderado = resultado["ponderado_pelos_estratos"]
    video = resultado["bootstrap_por_video"]["ic95_f1_macro"]
    idioma = resultado["sem_filtro_de_idioma"]

    def f(x: float) -> str:
        return f"{x:.3f}".replace(".", ",")

    def ic(par: list[float]) -> str:
        return f"[{f(par[0])}; {f(par[1])}]"

    linhas = [
        "| Método | F1 macro (publicado) | IC 95% por vídeo | F1 macro ponderado [IC 95%] "
        "| Acurácia ponderada | F1 sem os descartados pelo idioma |",
        "|---|---|---|---|---|---|",
    ]
    for nome in publicado:
        linhas.append(
            f"| {nome} | {f(publicado[nome]['f1_macro'])} | {ic(video[nome])} | "
            f"{f(ponderado[nome]['f1_macro'])} {ic(ponderado[nome]['ic95_f1_macro'])} | "
            f"{f(ponderado[nome]['acuracia'])} | {f(idioma[nome]['f1_macro'])} |"
        )
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exemplos", type=Path, required=True)
    parser.add_argument("--previsoes", action="append", default=[])
    parser.add_argument(
        "--descartados-idioma", type=Path, default=SAIDA_PADRAO / "descartados_idioma.csv"
    )
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    argumentos = parser.parse_args(argv)

    previsoes = {}
    for especificacao in argumentos.previsoes:
        nome, _, caminho = especificacao.partition("=")
        if not caminho:
            raise SystemExit(f"--previsoes espera nome=caminho.csv, veio {especificacao!r}")
        rotulos, problemas = ler_csv(Path(caminho), nome)
        if problemas:
            raise SystemExit("\n".join(str(p) for p in problemas))
        previsoes[nome] = rotulos

    descartados: set[int] = set()
    if argumentos.descartados_idioma.exists():
        with argumentos.descartados_idioma.open(encoding="utf-8") as arquivo:
            descartados = {int(linha["id_comentario"]) for linha in csv.DictReader(arquivo)}

    resultado = analisar(ler_exemplos(argumentos.exemplos), previsoes, descartados)
    resultado = {
        "data_utc": datetime.now(UTC).isoformat(),
        "aviso": "so ids, rotulos e metricas: nenhum texto de comentario",
        "bootstrap": {
            "reamostragens": REAMOSTRAGENS,
            "confianca": CONFIANCA,
            "semente": SEMENTE,
            "metodo": "percentil",
        },
        **resultado,
    }
    argumentos.saida.mkdir(parents=True, exist_ok=True)
    (argumentos.saida / "resultado_sensibilidade.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (argumentos.saida / "tabela_sensibilidade.md").write_text(
        tabela_markdown(resultado), encoding="utf-8"
    )
    print(tabela_markdown(resultado))
    return 0


if __name__ == "__main__":
    sys.exit(main())
