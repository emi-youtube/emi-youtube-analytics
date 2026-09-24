"""Converte o modelo treinado para ONNX int8 e mede se ele cabe no Azure B1.

**A pergunta que este script responde** não é "quanto o modelo acerta" — é "o backend
roda numa instância B1 (1 vCPU, 1,75 GB)?". O crédito do Azure for Students não paga
mais que isso, e um BERT em float32 ocupa ~440 MB de disco e sobe de 1 GB de RAM com
o runtime junto. A quantização dinâmica para int8 corta o peso para cerca de um quarto
e acelera a inferência em CPU, ao custo de alguma precisão numérica.

**Quanto custa é medido, não estimado.** O portão: perder no máximo **1 ponto de F1
macro** na validação em relação ao modelo original. Acima disso a economia não vale, e
o relatório sai com `aprovado: false`.

O que é medido, e por quê:

| número | decide |
|---|---|
| F1 macro (original x int8) | se a quantização estragou o modelo |
| divergência de previsão | quantos rótulos mudam (o F1 empata, o erro troca de lugar) |
| latência mediana e p95, lote 1, CPU | se a fila vence 5.000 comentários em tempo razoável |
| pico de RSS | se cabe em 1,75 GB com FastAPI e driver do Postgres do lado |

A comparação é feita **na validação**, com rótulo fraco. Isso é suficiente e correto:
a pergunta aqui é "o int8 responde igual ao float32?", e ela não depende de o rótulo
estar certo — depende de os dois modelos concordarem entre si. O conjunto de teste
continua intocado (CLAUDE.md regra 6).

Uso:
    python -m ml.treino.exportar_onnx --id-execucao 4 --modelo ml/modelos/bertimbau-ensaio
"""

import argparse
import asyncio
import json
import logging
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy
import onnxruntime
import psutil
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from ml.avaliacao.metricas import avaliar_previsoes
from ml.config import CLASSES, DIRETORIO_ML
from ml.treino.dados import Exemplo, carregar_exemplos, dividir_estratificado

logger = logging.getLogger("onnx")

ARQUIVO_RELATORIO = DIRETORIO_ML / "treino" / "relatorio_onnx.json"

# Portão desta conversão: 1 ponto de F1 macro.
PERDA_MAXIMA_F1 = 0.01

# Acima disto, a divergência de previsão vira aviso. Não é portão — o portão é o F1 —,
# mas F1 igual com muitas previsões trocadas significa que o int8 acerta OUTROS
# comentários, e não os mesmos. Num modelo mal treinado (ou no teste de fumaça) os
# logits ficam quase empatados e qualquer ruído numérico vira troca de rótulo; num
# modelo convergido, divergência alta é sintoma de quantização ruim.
DIVERGENCIA_SUSPEITA = 0.02

# Opset 14: é o primeiro que cobre todos os operadores que o BERT usa sem precisar de
# fallback, e é suportado pelo onnxruntime que o backend vai instalar.
OPSET = 14

# Quantas vezes cada comentário é classificado na medição de latência. A primeira
# passada de uma sessão ONNX é sempre mais lenta (alocação de arena, escolha de
# kernel), então ela é descartada e o resto vira mediana e p95.
REPETICOES_LATENCIA = 3
AQUECIMENTO = 5


@dataclass(frozen=True)
class Medicao:
    """O que um modelo entregou: qualidade, tempo e memória."""

    nome: str
    f1_macro: float
    acuracia: float
    f1_por_classe: dict[str, float]
    previsoes: list[str]
    latencia_mediana_ms: float
    latencia_p95_ms: float
    tamanho_mb: float
    pico_rss_mb: float


def tamanho_em_mb(caminho: Path, ignorar: Path | None = None) -> float:
    """Tamanho de um arquivo ou de uma pasta, em MB.

    `ignorar` existe porque a pasta do ONNX nasce DENTRO da pasta do modelo: sem
    excluí-la, o modelo PyTorch apareceria com o próprio tamanho somado ao dos dois
    grafos exportados, e a comparação de tamanho — que é a que decide a instância do
    Azure — sairia inflada em três vezes.
    """
    if caminho.is_file():
        return caminho.stat().st_size / 1_048_576
    arquivos = [item for item in caminho.rglob("*") if item.is_file()]
    if ignorar is not None:
        arquivos = [item for item in arquivos if ignorar not in item.parents]
    return sum(item.stat().st_size for item in arquivos) / 1_048_576


def pico_rss_mb() -> float:
    """Memória residente do processo agora, em MB.

    RSS e não `tracemalloc`: o peso do modelo vive em buffers nativos (torch e
    onnxruntime), que o rastreador do Python não enxerga. O número que interessa para
    o B1 é o que o sistema operacional cobra.
    """
    return psutil.Process().memory_info().rss / 1_048_576


def exportar(modelo_dir: Path, destino: Path, max_length: int) -> Path:
    """Exporta o modelo PyTorch para ONNX com eixos dinâmicos.

    `batch` e `sequence` ficam dinâmicos porque o worker de inferência vai mandar
    lotes de tamanho variável e textos de comprimento variável. Fixar os eixos daria
    um grafo mais rápido e um modelo que só aceita exatamente o formato do exemplo de
    exportação.
    """
    modelo = AutoModelForSequenceClassification.from_pretrained(modelo_dir)
    modelo.eval()
    tokenizador = AutoTokenizer.from_pretrained(modelo_dir)

    exemplo = tokenizador(
        "exemplo de comentario para tracar o grafo",
        return_tensors="pt",
        truncation=True,
        max_length=max_length,
    )
    entradas = ("input_ids", "attention_mask", "token_type_ids")
    eixos = {nome: {0: "batch", 1: "sequence"} for nome in entradas}
    eixos["logits"] = {0: "batch"}

    destino.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        modelo,
        args=(exemplo["input_ids"], exemplo["attention_mask"], exemplo["token_type_ids"]),
        f=str(destino),
        input_names=list(entradas),
        output_names=["logits"],
        dynamic_axes=eixos,
        opset_version=OPSET,
        do_constant_folding=True,
    )
    logger.info("onnx fp32 -> %s (%.1f MB)", destino, tamanho_em_mb(destino))
    return destino


def quantizar(origem: Path, destino: Path) -> Path:
    """Quantização **dinâmica** para int8.

    Dinâmica e não estática: a estática exigiria um conjunto de calibração e daria um
    ganho menor num modelo de atenção, onde o peso das matrizes densas é o que domina.
    A dinâmica quantiza os pesos uma vez e calcula a escala das ativações em tempo de
    execução — é a receita padrão para BERT em CPU.
    """
    quantize_dynamic(
        model_input=str(origem),
        model_output=str(destino),
        weight_type=QuantType.QInt8,
    )
    logger.info("onnx int8 -> %s (%.1f MB)", destino, tamanho_em_mb(destino))
    return destino


def _lotes(exemplos: list[Exemplo], tamanho: int):
    for inicio in range(0, len(exemplos), tamanho):
        yield exemplos[inicio : inicio + tamanho]


def medir_pytorch(
    modelo_dir: Path, exemplos: list[Exemplo], max_length: int, lote: int, export_dir: Path
) -> Medicao:
    """Roda o modelo original em CPU: qualidade, latência e memória.

    **Uma thread, como o ONNX.** O `torch` usa todos os núcleos da máquina por padrão
    e o `onnxruntime` está preso a um aqui de propósito (o B1 tem 1 vCPU): sem
    igualar, a comparação mediria o número de núcleos da máquina de desenvolvimento,
    não a diferença entre os dois formatos.
    """
    torch.set_num_threads(1)
    tokenizador = AutoTokenizer.from_pretrained(modelo_dir)
    modelo = AutoModelForSequenceClassification.from_pretrained(modelo_dir)
    modelo.eval()

    previstos: list[str] = []
    with torch.no_grad():
        for grupo in _lotes(exemplos, lote):
            entrada = tokenizador(
                [exemplo.texto_modelo for exemplo in grupo],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            logits = modelo(**entrada).logits
            previstos.extend(CLASSES[indice] for indice in logits.argmax(dim=-1).tolist())

    def uma_previsao(texto: str) -> None:
        entrada = tokenizador(
            texto, truncation=True, max_length=max_length, return_tensors="pt"
        )
        with torch.no_grad():
            modelo(**entrada)

    latencias = medir_latencia(uma_previsao, exemplos)
    verdadeiros = [exemplo.rotulo for exemplo in exemplos]
    metricas = avaliar_previsoes(verdadeiros, previstos, CLASSES)

    return Medicao(
        nome="pytorch fp32",
        f1_macro=metricas.f1_macro,
        acuracia=metricas.acuracia,
        f1_por_classe={classe: m.f1 for classe, m in metricas.por_classe.items()},
        previsoes=previstos,
        latencia_mediana_ms=latencias[0],
        latencia_p95_ms=latencias[1],
        tamanho_mb=tamanho_em_mb(modelo_dir, ignorar=export_dir),
        pico_rss_mb=pico_rss_mb(),
    )


def medir_onnx(
    caminho: Path, modelo_dir: Path, exemplos: list[Exemplo], max_length: int, lote: int, nome: str
) -> Medicao:
    """Roda um modelo ONNX com **uma thread** — é o que a instância B1 tem.

    Medir com todas as threads da máquina de desenvolvimento daria um número que a
    produção nunca vai reproduzir: o B1 é 1 vCPU.
    """
    tokenizador = AutoTokenizer.from_pretrained(modelo_dir)
    opcoes = onnxruntime.SessionOptions()
    opcoes.intra_op_num_threads = 1
    opcoes.inter_op_num_threads = 1
    sessao = onnxruntime.InferenceSession(
        str(caminho), sess_options=opcoes, providers=["CPUExecutionProvider"]
    )

    def entradas_de(textos: list[str]) -> dict[str, numpy.ndarray]:
        codificado = tokenizador(
            textos, padding=True, truncation=True, max_length=max_length, return_tensors="np"
        )
        return {
            entrada.name: codificado[entrada.name].astype(numpy.int64)
            for entrada in sessao.get_inputs()
        }

    previstos: list[str] = []
    for grupo in _lotes(exemplos, lote):
        logits = sessao.run(None, entradas_de([exemplo.texto_modelo for exemplo in grupo]))[0]
        previstos.extend(CLASSES[indice] for indice in logits.argmax(axis=-1).tolist())

    latencias = medir_latencia(lambda texto: sessao.run(None, entradas_de([texto])), exemplos)
    verdadeiros = [exemplo.rotulo for exemplo in exemplos]
    metricas = avaliar_previsoes(verdadeiros, previstos, CLASSES)

    return Medicao(
        nome=nome,
        f1_macro=metricas.f1_macro,
        acuracia=metricas.acuracia,
        f1_por_classe={classe: m.f1 for classe, m in metricas.por_classe.items()},
        previsoes=previstos,
        latencia_mediana_ms=latencias[0],
        latencia_p95_ms=latencias[1],
        tamanho_mb=tamanho_em_mb(caminho),
        pico_rss_mb=pico_rss_mb(),
    )


def medir_latencia(classificar, exemplos: list[Exemplo]) -> tuple[float, float]:
    """Latência de UM comentário por vez — o caso do worker, que processa em fila.

    Mediana e p95, e não média: o tempo por comentário depende do comprimento dele, e
    a média de uma distribuição com cauda longa não descreve nem o caso comum nem o
    ruim. O p95 é o que dimensiona a fila.
    """
    amostra = exemplos[: min(len(exemplos), 60)]
    for exemplo in amostra[:AQUECIMENTO]:
        classificar(exemplo.texto_modelo)

    tempos: list[float] = []
    for _ in range(REPETICOES_LATENCIA):
        for exemplo in amostra:
            inicio = time.perf_counter()
            classificar(exemplo.texto_modelo)
            tempos.append((time.perf_counter() - inicio) * 1000)

    tempos.sort()
    p95 = tempos[min(int(len(tempos) * 0.95), len(tempos) - 1)]
    return statistics.median(tempos), p95


def divergencia(uma: Medicao, outra: Medicao) -> int:
    """Quantos comentários os dois modelos rotulam diferente.

    O F1 pode empatar com os erros trocando de lugar; este número mostra isso.
    """
    return sum(1 for a, b in zip(uma.previsoes, outra.previsoes, strict=True) if a != b)


def relatar(medicoes: list[Medicao], base: Medicao, quantidade: int) -> None:
    logger.info("")
    logger.info("=" * 78)
    logger.info("ONNX int8 - validacao com %s comentarios, CPU 1 thread", quantidade)
    logger.info("=" * 78)
    logger.info(
        "%-16s %10s %10s %12s %10s %10s",
        "modelo",
        "F1 macro",
        "acuracia",
        "mediana ms",
        "p95 ms",
        "tamanho MB",
    )
    logger.info("-" * 78)
    for medicao in medicoes:
        logger.info(
            "%-16s %10.4f %10.4f %12.1f %10.1f %10.1f",
            medicao.nome,
            medicao.f1_macro,
            medicao.acuracia,
            medicao.latencia_mediana_ms,
            medicao.latencia_p95_ms,
            medicao.tamanho_mb,
        )

    logger.info("")
    for medicao in medicoes:
        if medicao is base:
            continue
        perda = base.f1_macro - medicao.f1_macro
        ganho = base.latencia_mediana_ms / medicao.latencia_mediana_ms
        logger.info(
            "%s vs %s: F1 macro %+.4f | %.1fx mais rapido | %.0f%% do tamanho | "
            "%d/%d previsoes diferentes",
            medicao.nome,
            base.nome,
            -perda,
            ganho,
            100 * medicao.tamanho_mb / base.tamanho_mb,
            divergencia(base, medicao),
            quantidade,
        )
        situacao = "APROVADO" if perda <= PERDA_MAXIMA_F1 else "REPROVADO"
        logger.info(
            "  portao (perder no maximo %.0f ponto de F1 macro): %s",
            PERDA_MAXIMA_F1 * 100,
            situacao,
        )
        trocadas = divergencia(base, medicao) / quantidade
        if trocadas > DIVERGENCIA_SUSPEITA:
            logger.warning(
                "  ATENCAO: %.0f%% das previsoes mudaram com F1 praticamente igual. "
                "O modelo acerta OUTROS comentarios, nao os mesmos — confira se ele "
                "esta convergido antes de aceitar o int8.",
                100 * trocadas,
            )
    logger.info("=" * 78)


def gravar_relatorio(
    medicoes: list[Medicao], base: Medicao, quantidade: int, caminho: Path
) -> None:
    """JSON de agregados — versionado. É o que decide a instância do Azure."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    int8 = next((medicao for medicao in medicoes if "int8" in medicao.nome), None)
    conteudo = {
        "aviso": (
            "medido na VALIDACAO com rotulo fraco. A pergunta aqui e se o int8 "
            "responde como o fp32, nao quanto o modelo acerta — isso e o Capitulo 5."
        ),
        "comentarios_avaliados": quantidade,
        "threads": 1,
        "portao_perda_f1_macro": PERDA_MAXIMA_F1,
        "modelos": [
            {
                "nome": medicao.nome,
                "f1_macro": medicao.f1_macro,
                "acuracia": medicao.acuracia,
                "f1_por_classe": medicao.f1_por_classe,
                "latencia_mediana_ms": round(medicao.latencia_mediana_ms, 2),
                "latencia_p95_ms": round(medicao.latencia_p95_ms, 2),
                "tamanho_mb": round(medicao.tamanho_mb, 1),
                "pico_rss_mb": round(medicao.pico_rss_mb, 1),
                # Divergencia contra a base, por formato. O `relatar()` ja imprimia
                # este numero para os dois formatos convertidos, mas so o do int8
                # sobrevivia no JSON — e e o do fp32 que responde "a conversao para
                # ONNX, sozinha, mudou alguma coisa?". Zero aqui e o que separa "o
                # int8 degradou" de "a exportacao degradou".
                "previsoes_diferentes_da_base": (
                    None if medicao.nome == base.nome else divergencia(base, medicao)
                ),
            }
            for medicao in medicoes
        ],
    }
    if int8 is not None:
        perda = base.f1_macro - int8.f1_macro
        trocadas = divergencia(base, int8)
        conteudo["int8_vs_fp32"] = {
            "perda_f1_macro": perda,
            "aprovado": perda <= PERDA_MAXIMA_F1,
            "previsoes_diferentes": trocadas,
            "fracao_previsoes_diferentes": trocadas / quantidade,
            # O portao e o F1, e ele pode passar com os erros so trocando de lugar.
            # Este campo existe para que a ressalva viva no arquivo versionado, e nao
            # so no log de quem rodou: `aprovado: true` com divergencia alta significa
            # que o int8 acerta OUTROS comentarios, nao os mesmos.
            "divergencia_suspeita": trocadas / quantidade > DIVERGENCIA_SUSPEITA,
            "limite_divergencia_suspeita": DIVERGENCIA_SUSPEITA,
            "aceleracao_mediana": base.latencia_mediana_ms / int8.latencia_mediana_ms,
            "fracao_do_tamanho": int8.tamanho_mb / base.tamanho_mb,
        }
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("relatorio -> %s", caminho)


def exigir_modelo_treinado(modelo_dir: Path) -> None:
    """Confere que `--modelo` aponta para uma pasta com modelo ANTES de exportar.

    Foi este o erro do Colab, e o rastro que ele deixava não dizia o que tinha
    acontecido: `FileNotFoundError: ml/modelos/bertimbau-ensaio/model_card.json`, sem
    dizer em qual cópia do repositório o interpretador estava procurando. `--modelo`
    veio relativo, o kernel tinha mudado de diretório, e `ml/modelos/` não existe num
    clone novo — a pasta inteira está no `.gitignore`. A mensagem agora mostra o
    caminho ABSOLUTO que ele procurou, que é o que separa "o treino não rodou" de "o
    treino rodou na outra cópia".
    """
    if (modelo_dir / "model_card.json").exists():
        return
    raise SystemExit(
        f"nao ha modelo em {modelo_dir.resolve()} (sem model_card.json). "
        "Rode o treino antes, e confira se este e mesmo o diretorio onde ele gravou: "
        "ml/modelos/ nao vem no clone (esta no .gitignore), entao um caminho relativo "
        "resolvido a partir de outro diretorio aponta para uma pasta vazia."
    )


def medir_em_subprocesso(formato: str, argumentos: argparse.Namespace, destino: Path) -> Medicao:
    """Mede um formato num processo NOVO, e é por causa da RAM.

    Os três modelos rodando no mesmo processo dariam um número de memória sem
    sentido: quando a sessão ONNX sobe, o BERT do PyTorch ainda está carregado, e o
    RSS medido para o ONNX seria o dos dois somados. Na primeira medição isto apareceu
    como 1.158 MB para um grafo de 416 MB — e é justamente esse número que decide se o
    backend cabe numa instância B1 de 1,75 GB.

    Processo novo por formato: cada um carrega só o que precisa, e o RSS que sai é o
    que o Azure vai cobrar.
    """
    comando = [
        sys.executable,
        "-m",
        "ml.treino.exportar_onnx",
        "--medir",
        formato,
        "--id-execucao",
        str(argumentos.id_execucao),
        "--modelo",
        str(argumentos.modelo),
        "--saida",
        str(destino),
        "--lote",
        str(argumentos.lote),
    ]
    if argumentos.limite:
        comando += ["--limite", str(argumentos.limite)]

    processo = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8")
    if processo.returncode != 0:
        raise SystemExit(
            f"medicao de '{formato}' falhou:\n{processo.stderr[-2000:]}"
        )

    # O filho imprime o JSON na ultima linha; o resto da saida dele e log.
    linhas = [linha for linha in processo.stdout.splitlines() if linha.strip()]
    return Medicao(**json.loads(linhas[-1]))


def executar_medicao(
    formato: str, argumentos: argparse.Namespace, max_length: int, destino: Path
) -> Medicao:
    """O lado filho: mede UM formato e devolve. Nada de relatório aqui."""
    exemplos = asyncio.run(carregar_exemplos(argumentos.id_execucao))
    validacao = dividir_estratificado(exemplos).validacao
    if argumentos.limite:
        validacao = validacao[: argumentos.limite]

    if formato == "pytorch":
        return medir_pytorch(argumentos.modelo, validacao, max_length, argumentos.lote, destino)
    caminho = destino / ("modelo.onnx" if formato == "onnx-fp32" else "modelo_int8.onnx")
    nome = "onnx fp32" if formato == "onnx-fp32" else "onnx int8"
    return medir_onnx(
        caminho, argumentos.modelo, validacao, max_length, argumentos.lote, nome
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument("--modelo", type=Path, required=True, help="pasta do modelo treinado")
    parser.add_argument("--saida", type=Path, default=None, help="padrao: <modelo>/onnx")
    parser.add_argument("--lote", type=int, default=16)
    parser.add_argument(
        "--limite", type=int, default=None, help="usa so os N primeiros da validacao"
    )
    parser.add_argument("--relatorio", type=Path, default=ARQUIVO_RELATORIO)
    parser.add_argument(
        "--medir",
        choices=("pytorch", "onnx-fp32", "onnx-int8"),
        default=None,
        help="uso interno: mede um formato so e imprime JSON (ver medir_em_subprocesso)",
    )
    argumentos = parser.parse_args()

    # O filho escreve log no stderr e SO o JSON no stdout — e o stdout que o pai le.
    logging.basicConfig(
        level="INFO",
        format="%(message)s",
        stream=sys.stderr if argumentos.medir else sys.stdout,
    )

    exigir_modelo_treinado(argumentos.modelo)
    cartao = json.loads((argumentos.modelo / "model_card.json").read_text(encoding="utf-8"))
    max_length = cartao["max_length"]
    # A ordem dos rotulos vem do cartao, nunca do codigo (CLAUDE.md regra 5). Aqui ela
    # e conferida contra a do projeto: se divergir, as previsoes sairiam trocadas.
    ordem_do_cartao = tuple(
        cartao["id2label"][str(indice)] for indice in range(len(cartao["id2label"]))
    )
    if ordem_do_cartao != CLASSES:
        raise SystemExit(
            f"id2label do model_card ({ordem_do_cartao}) difere da ordem do projeto "
            f"({CLASSES}). Reexporte o modelo antes de converter."
        )

    destino = argumentos.saida or (argumentos.modelo / "onnx")

    if argumentos.medir:
        medicao = executar_medicao(argumentos.medir, argumentos, max_length, destino)
        print(json.dumps(medicao.__dict__, ensure_ascii=False))
        return

    fp32 = exportar(argumentos.modelo, destino / "modelo.onnx", max_length)
    quantizar(fp32, destino / "modelo_int8.onnx")

    medicoes = [
        medir_em_subprocesso(formato, argumentos, destino)
        for formato in ("pytorch", "onnx-fp32", "onnx-int8")
    ]
    base = medicoes[0]
    quantidade = len(base.previsoes)

    relatar(medicoes, base, quantidade)
    gravar_relatorio(medicoes, base, quantidade, argumentos.relatorio)


if __name__ == "__main__":
    main()
