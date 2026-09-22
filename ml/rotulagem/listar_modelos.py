"""Lista os modelos que a `GEMINI_API_KEY` de `ml/.env` enxerga. OFFLINE.

Rode ANTES de escolher o `GEMINI_MODELO`. O catálogo da Gemini muda: modelo é
aposentado, entra em preview, vira apelido. Assumir que o nome de ontem existe hoje
é como uma rodada de rotulagem morre com HTTP 404 no meio.

Marca com `*` o que serve para uma rodada reproduzível: suporta `generateContent`,
não é preview nem experimental, e não é apelido `-latest` (apelido aponta para outro
modelo quando o Google troca o alvo — o metadado registraria um nome que não
descreve o que de fato rodou).

Uso:
    python -m ml.rotulagem.listar_modelos
    python -m ml.rotulagem.listar_modelos --todos   # inclui preview e apelidos
"""

import argparse
import logging
import sys

from ml.config import chave_gemini
from ml.rotulagem.gemini import e_estavel, listar_modelos

logger = logging.getLogger("listar_modelos")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--todos", action="store_true", help="mostra tambem preview, experimental e -latest"
    )
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    modelos = [m for m in listar_modelos(chave_gemini()) if "generateContent" in m["metodos"]]
    estaveis = [m for m in modelos if e_estavel(m["nome"])]

    logger.info("modelos com generateContent: %s (estaveis: %s)", len(modelos), len(estaveis))
    logger.info("-" * 72)
    for modelo in modelos:
        marca = "*" if e_estavel(modelo["nome"]) else " "
        if marca == " " and not argumentos.todos:
            continue
        logger.info("%s %-42s %s", marca, modelo["nome"], modelo["rotulo"])
    logger.info("-" * 72)
    logger.info("* = serve para rodada reproduzivel. Escreva o nome exato em ml/.env:")
    logger.info("  GEMINI_MODELO=<nome>")


if __name__ == "__main__":
    main()
