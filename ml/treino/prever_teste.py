"""Classifica os 334 do conjunto de teste e guarda as previsões. Uma única vez, no fim.

Este é o script que "olha o teste" — e ele foi escrito para olhar o menos possível:
**carrega os comentários sem os rótulos** (`ml.treino.dados.carregar_teste` não traz
`rotulo_humano` nem `rotulo_fraco`), classifica e grava. Nenhuma métrica sai daqui.
A comparação contra o gabarito é trabalho de `ml/avaliacao/`, que é um processo
separado, rodado depois.

A separação não é cerimônia. Se este script imprimisse a acurácia no teste, a
tentação de voltar e mexer num hiperparâmetro seria imediata — e aí o teste teria
virado um segundo conjunto de validação, com as métricas do Capítulo 5 perdendo o
sentido que o TC2 atribui a elas.

**A ordem dos rótulos vem do `model_card.json`** (CLAUDE.md regra 5), nunca de uma
lista escrita aqui. É o mesmo contrato que o worker de inferência vai cumprir.

Saída: CSV com `id_comentario`, `previsto` e `confianca` — o formato que
`ml/avaliacao/avaliar.py` consome de qualquer método.

Uso:
    python -m ml.treino.prever_teste --id-execucao 4 --modelo ml/modelos/bertimbau-ensaio
    python -m ml.treino.prever_teste --id-execucao 4 --modelo ml/modelos/bertimbau-ensaio \\
        --onnx ml/modelos/bertimbau-ensaio/onnx/modelo_int8.onnx
"""

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path

from ml.config import DIRETORIO_DADOS
from ml.treino.dados import Exemplo, carregar_teste

logger = logging.getLogger("prever")

ARQUIVO_PREVISOES = DIRETORIO_DADOS / "previsoes_bertimbau.csv"

COLUNAS_CSV = ("id_comentario", "previsto", "confianca")


def ler_cartao(modelo_dir: Path) -> tuple[tuple[str, ...], int]:
    """Ordem dos rótulos e `max_length`, do cartão que veio com os pesos."""
    cartao = json.loads((modelo_dir / "model_card.json").read_text(encoding="utf-8"))
    id2label = cartao["id2label"]
    classes = tuple(id2label[str(indice)] for indice in range(len(id2label)))
    return classes, cartao["max_length"]


def _lotes(exemplos: list[Exemplo], tamanho: int):
    for inicio in range(0, len(exemplos), tamanho):
        yield exemplos[inicio : inicio + tamanho]


def prever_pytorch(
    modelo_dir: Path, exemplos: list[Exemplo], classes: tuple[str, ...], max_length: int, lote: int
) -> list[tuple[str, float]]:
    """Previsão com os pesos em float32 — o caminho do Colab e do teste local."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizador = AutoTokenizer.from_pretrained(modelo_dir)
    modelo = AutoModelForSequenceClassification.from_pretrained(modelo_dir)
    modelo.eval()

    saidas: list[tuple[str, float]] = []
    with torch.no_grad():
        for grupo in _lotes(exemplos, lote):
            entrada = tokenizador(
                [exemplo.texto_modelo for exemplo in grupo],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            probabilidades = modelo(**entrada).logits.softmax(dim=-1)
            for linha in probabilidades:
                indice = int(linha.argmax())
                saidas.append((classes[indice], float(linha[indice])))
    return saidas


def prever_onnx(
    caminho: Path,
    modelo_dir: Path,
    exemplos: list[Exemplo],
    classes: tuple[str, ...],
    max_length: int,
    lote: int,
) -> list[tuple[str, float]]:
    """Previsão com o grafo ONNX — o artefato que o backend vai de fato carregar.

    Existe para que a previsão do Capítulo 5 possa sair do MESMO arquivo que roda em
    produção. Medir um modelo e publicar outro é o tipo de diferença que ninguém nota
    até o número não bater.
    """
    import numpy
    import onnxruntime
    from transformers import AutoTokenizer

    tokenizador = AutoTokenizer.from_pretrained(modelo_dir)
    sessao = onnxruntime.InferenceSession(str(caminho), providers=["CPUExecutionProvider"])

    saidas: list[tuple[str, float]] = []
    for grupo in _lotes(exemplos, lote):
        codificado = tokenizador(
            [exemplo.texto_modelo for exemplo in grupo],
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="np",
        )
        entradas = {
            entrada.name: codificado[entrada.name].astype(numpy.int64)
            for entrada in sessao.get_inputs()
        }
        logits = sessao.run(None, entradas)[0]
        expoente = numpy.exp(logits - logits.max(axis=-1, keepdims=True))
        probabilidades = expoente / expoente.sum(axis=-1, keepdims=True)
        for linha in probabilidades:
            indice = int(linha.argmax())
            saidas.append((classes[indice], float(linha[indice])))
    return saidas


def gravar(
    exemplos: list[Exemplo], previsoes: list[tuple[str, float]], caminho: Path
) -> None:
    """CSV no formato que `ml/avaliacao/avaliar.py` lê de qualquer método."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # newline="" é exigência do csv no Windows: sem isso sai \r\r\n entre as linhas.
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(COLUNAS_CSV)
        for exemplo, (rotulo, confianca) in zip(exemplos, previsoes, strict=True):
            escritor.writerow([exemplo.id_comentario, rotulo, f"{confianca:.4f}"])
    logger.info("previsoes -> %s (%s linhas)", caminho, len(exemplos))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument("--modelo", type=Path, required=True)
    parser.add_argument(
        "--onnx", type=Path, default=None, help="usa este grafo em vez dos pesos PyTorch"
    )
    parser.add_argument("--lote", type=int, default=16)
    parser.add_argument("--saida", type=Path, default=ARQUIVO_PREVISOES)
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    classes, max_length = ler_cartao(argumentos.modelo)
    logger.info("model_card: id2label=%s max_length=%s", list(classes), max_length)

    exemplos = asyncio.run(carregar_teste(argumentos.id_execucao))
    if not exemplos:
        raise SystemExit(
            f"nenhum exemplo com split='teste' na execucao {argumentos.id_execucao}."
        )

    if argumentos.onnx:
        previsoes = prever_onnx(
            argumentos.onnx, argumentos.modelo, exemplos, classes, max_length, argumentos.lote
        )
    else:
        previsoes = prever_pytorch(
            argumentos.modelo, exemplos, classes, max_length, argumentos.lote
        )

    gravar(exemplos, previsoes, argumentos.saida)
    logger.info("")
    logger.info("Nenhuma metrica foi calculada aqui, de proposito. Para compara-las com o")
    logger.info("gabarito humano:")
    logger.info(
        "  python -m ml.avaliacao.avaliar --id-execucao %s --previsoes bertimbau=%s --gemini",
        argumentos.id_execucao,
        argumentos.saida,
    )


if __name__ == "__main__":
    main()
