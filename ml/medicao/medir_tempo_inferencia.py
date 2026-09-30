"""Mede o tempo do BERTimbau classificando um lote de comentários, como o worker faria.

Responde à meta de tempo de resposta da Tabela 15 do TC2: **no máximo 3 minutos por
lote de 1.000 comentários**.

**O que é reproduzido do worker de inferência** (`backend/app/workers/inferencia.py`):

- um comentário por vez. O worker chama `classificador.classificar(texto)` para cada
  comentário, sem montar lote de tensor — então aqui também é lote de 1, sem padding;
- `preparar_texto` aplicado DENTRO do laço cronometrado, sobre o texto ORIGINAL — é o
  worker que o aplica, e o custo é dele;
- pesos em ponto flutuante de 32 bits, PyTorch (o formato decidido; o int8 foi
  reprovado — `ml/treino/README.md`);
- `id2label` e `max_length` lidos do `model_card.json` (CLAUDE.md regra 5).

**O que simula a B1 do Azure** (1 vCPU, 1,75 GB): o processo é preso a UM núcleo lógico
(afinidade de CPU) e o `torch` a uma thread. Sem isso, o `torch` usa todos os núcleos
da máquina de desenvolvimento, e o número medido seria o da máquina, não o da
hospedagem — o mesmo erro que a primeira medição do ONNX cometeu.

**O que NÃO entra no tempo:** leitura dos comentários e gravação das análises no banco.
Isso é E/S do Postgres, e não depende do classificador; o carregamento do modelo é
medido à parte, porque acontece uma vez na subida do worker e não por lote.

Um núcleo de uma máquina de mesa não é um vCPU de nuvem: o número daqui é o de uma
simulação, e a metodologia vai junto no relatório para que isso fique explícito.

Uso:
    python -m ml.medicao.medir_tempo_inferencia --modelo ml/modelos/<pasta>
"""

import argparse
import csv
import json
import logging
import platform
import random
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from preprocessamento import VERSAO as VERSAO_PREPROCESSAMENTO
from preprocessamento import preparar_texto

from ml.config import DIRETORIO_DADOS, DIRETORIO_ML, SEMENTE

logger = logging.getLogger("medir_tempo_inferencia")

ARQUIVO_CORPUS = DIRETORIO_DADOS / "corpus.csv"
ARQUIVO_PREVISOES = DIRETORIO_DADOS / "previsoes_bertimbau.csv"
SAIDA_PADRAO = DIRETORIO_ML / "medicao" / "relatorio_tempo_inferencia.json"

# A meta da Tabela 15 do TC2.
META_SEGUNDOS = 180.0
TAMANHO_META = 1000


def fixar_em_um_nucleo(nucleo: int) -> list[int]:
    """Prende o processo a um núcleo lógico, ANTES de o torch criar as threads dele."""
    import psutil

    processo = psutil.Process()
    processo.cpu_affinity([nucleo])
    return processo.cpu_affinity()


def nome_da_cpu() -> str:
    """Nome comercial da CPU; `platform.processor()` no Windows só dá a família."""
    if platform.system() == "Windows":
        import winreg

        chave = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        return str(winreg.QueryValueEx(chave, "ProcessorNameString")[0]).strip()
    return platform.processor()


def ler_corpus() -> list[tuple[int, str, str]]:
    """(id_comentario, texto original, texto_modelo) do corpus exportado."""
    with ARQUIVO_CORPUS.open(encoding="utf-8", newline="") as arquivo:
        return [
            (int(linha["id_comentario"]), linha["texto"], linha["texto_modelo"])
            for linha in csv.DictReader(arquivo)
        ]


def percentil(valores: list[float], p: float) -> float:
    ordenados = sorted(valores)
    posicao = (len(ordenados) - 1) * p / 100
    baixo = int(posicao)
    alto = min(baixo + 1, len(ordenados) - 1)
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * (posicao - baixo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", type=Path, required=True)
    parser.add_argument("--quantidade", type=int, default=TAMANHO_META)
    parser.add_argument("--repeticoes", type=int, default=3)
    parser.add_argument("--nucleo", type=int, default=0, help="nucleo logico da afinidade")
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    afinidade = fixar_em_um_nucleo(argumentos.nucleo)

    import psutil
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)

    cartao = json.loads((argumentos.modelo / "model_card.json").read_text(encoding="utf-8"))
    id2label = cartao["id2label"]
    classes = tuple(id2label[str(indice)] for indice in range(len(id2label)))
    max_length = cartao["max_length"]
    if cartao["versao_preprocessamento"] != VERSAO_PREPROCESSAMENTO:
        raise SystemExit(
            f"modelo medido com preprocessamento {cartao['versao_preprocessamento']}, "
            f"instalado {VERSAO_PREPROCESSAMENTO}: o worker recusaria este modelo"
        )

    inicio = time.perf_counter()
    tokenizador = AutoTokenizer.from_pretrained(argumentos.modelo)
    modelo = AutoModelForSequenceClassification.from_pretrained(argumentos.modelo)
    modelo.eval()
    segundos_carga = time.perf_counter() - inicio

    def classificar(texto_original: str) -> str:
        """O caminho de UM comentário no worker: preparar_texto -> modelo -> id2label."""
        entrada = tokenizador(
            preparar_texto(texto_original),
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        return classes[int(modelo(**entrada).logits.argmax(dim=-1))]

    corpus = ler_corpus()
    amostra = random.Random(SEMENTE).sample(corpus, argumentos.quantidade)

    # Conferência de identidade dos pesos, fora do cronômetro: o modelo carregado
    # precisa reproduzir as previsões publicadas do conjunto de teste. Sem ela, nada
    # garante que o tempo medido é o do modelo avaliado no Capítulo 5.
    conferencia = None
    if ARQUIVO_PREVISOES.exists():
        texto_por_id = {id_comentario: texto for id_comentario, texto, _ in corpus}
        with ARQUIVO_PREVISOES.open(encoding="utf-8", newline="") as arquivo:
            publicadas = {
                int(linha["id_comentario"]): linha["previsto"] for linha in csv.DictReader(arquivo)
            }
        with torch.inference_mode():
            iguais = sum(
                classificar(texto_por_id[id_comentario]) == rotulo
                for id_comentario, rotulo in publicadas.items()
            )
        conferencia = {"previsoes_publicadas": len(publicadas), "iguais": iguais}
        logger.info("conferencia dos pesos: %s/%s previsoes iguais", iguais, len(publicadas))

    rodadas = []
    with torch.inference_mode():
        for rodada in range(1, argumentos.repeticoes + 1):
            latencias: list[float] = []
            inicio_lote = time.perf_counter()
            for _, texto, _ in amostra:
                inicio = time.perf_counter()
                classificar(texto)
                latencias.append(time.perf_counter() - inicio)
            total = time.perf_counter() - inicio_lote
            rodadas.append(
                {
                    "rodada": rodada,
                    "segundos_total": total,
                    "comentarios_por_segundo": len(amostra) / total,
                    "latencia_ms_mediana": 1000 * statistics.median(latencias),
                    "latencia_ms_p95": 1000 * percentil(latencias, 95),
                    "latencia_ms_maxima": 1000 * max(latencias),
                }
            )
            logger.info(
                "rodada %s: %.1f s para %s comentarios (mediana %.1f ms, p95 %.1f ms)",
                rodada,
                total,
                len(amostra),
                rodadas[-1]["latencia_ms_mediana"],
                rodadas[-1]["latencia_ms_p95"],
            )

    pior = max(rodada["segundos_total"] for rodada in rodadas)
    # Normalizado para 1.000 comentários, para o caso de --quantidade diferente.
    pior_por_mil = pior * TAMANHO_META / len(amostra)
    # Pico do conjunto de trabalho: é o que a B1 cobra dos 1,75 GB. Só existe no Windows.
    memoria = psutil.Process().memory_info()
    rss_mb = memoria.peak_wset / 2**20 if hasattr(memoria, "peak_wset") else None

    relatorio = {
        "data_utc": datetime.now(UTC).isoformat(),
        "pergunta": "tempo de resposta da Tabela 15 do TC2: <= 3 min por lote de 1.000 comentarios",
        "modelo": {
            "pasta": argumentos.modelo.name,
            "versao": cartao["versao"],
            "semente": cartao["semente"],
            "treinado_em_utc": cartao.get("treinado_em_utc"),
            "formato": "pytorch float32",
        },
        "conferencia_dos_pesos": conferencia,
        "metodologia": {
            "onde": "maquina local simulando a B1 do Azure (1 vCPU, 1,75 GB)",
            "cpu": nome_da_cpu(),
            "nucleos_logicos_da_maquina": psutil.cpu_count(logical=True),
            "afinidade_do_processo": afinidade,
            "threads_torch": torch.get_num_threads(),
            "threads_interop_torch": torch.get_num_interop_threads(),
            "lote_do_modelo": 1,
            "preparar_texto_no_tempo": True,
            "banco_no_tempo": False,
            "comentarios": len(amostra),
            "amostra": f"sorteio sem reposicao do corpus, semente {SEMENTE}",
            "max_length": max_length,
            "torch": torch.__version__,
            "python": platform.python_version(),
            "so": platform.platform(),
        },
        "carga_do_modelo_segundos": segundos_carga,
        "rss_pico_mb": rss_mb,
        "rodadas": rodadas,
        "pior_rodada_segundos_por_1000": pior_por_mil,
        "meta_segundos_por_1000": META_SEGUNDOS,
        "dentro_da_meta": pior_por_mil <= META_SEGUNDOS,
    }
    argumentos.saida.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "pior rodada: %.1f s por 1.000 comentarios (meta %.0f s) -> %s",
        pior_por_mil,
        META_SEGUNDOS,
        "DENTRO da meta" if relatorio["dentro_da_meta"] else "FORA da meta",
    )
    logger.info("relatorio -> %s", argumentos.saida)


if __name__ == "__main__":
    main()
