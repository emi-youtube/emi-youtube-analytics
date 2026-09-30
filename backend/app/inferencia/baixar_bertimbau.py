"""Coloca os pesos do BERTimbau no servidor e CONFERE o sha256 antes de dar por bom.

`python -m app.inferencia.baixar_bertimbau` — chamado pelo `startup.sh`, antes do
runner. O mesmo padrão do `scripts/baixar_sentilex.sh`: baixa para um caminho
persistente (`/home` no App Service), só o que falta ou diverge, e só promove o
arquivo para o nome definitivo depois de conferir.

**De onde:** um repositório PRIVADO do Hugging Face Hub (`BERTIMBAU_REPO_HF`), lido
com `HF_TOKEN`. A decisão e a alternativa estão em docs/DEPLOY.md. A integridade não
depende da origem: quem manda é o `sha256` do manifesto versionado
(`bertimbau_manifesto.json`), então um repositório trocado ou um arquivo corrompido no
caminho falham aqui do mesmo jeito.

**Falhar aqui não derruba nada.** Sai com código 1 e uma mensagem; o `startup.sh`
segue, e o runner, sem o modelo, cai para o léxico (`workers/runner.py`).
"""

import logging
import sys
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.inferencia.bertimbau import ler_manifesto, sha256_de

logger = logging.getLogger("baixar_bertimbau")

URL_HF = "https://huggingface.co/{repo}/resolve/{revisao}/{arquivo}"

# Os pesos têm ~420 MB: o limite é por leitura parada, não pelo download inteiro.
TIMEOUT = httpx.Timeout(60.0, connect=15.0)


def baixar(
    destino: Path,
    repo: str,
    revisao: str,
    token: str,
    cliente: httpx.Client,
    manifesto: dict[str, Any] | None = None,
) -> list[str]:
    """Baixa o que falta ou diverge. Devolve os arquivos que ainda estão errados."""
    manifesto = manifesto if manifesto is not None else ler_manifesto()
    destino.mkdir(parents=True, exist_ok=True)
    cabecalhos = {"Authorization": f"Bearer {token}"} if token else {}

    com_problema: list[str] = []
    for nome, esperado in manifesto["arquivos"].items():
        final = destino / nome
        if final.is_file() and sha256_de(final) == esperado:
            logger.info("[bertimbau] ja presente e conferido: %s", nome)
            continue

        parcial = destino / f"{nome}.parcial"
        url = URL_HF.format(repo=repo, revisao=revisao, arquivo=nome)
        logger.info("[bertimbau] baixando %s", nome)
        try:
            with cliente.stream("GET", url, headers=cabecalhos, follow_redirects=True) as resposta:
                resposta.raise_for_status()
                with parcial.open("wb") as arquivo:
                    for bloco in resposta.iter_bytes(1 << 20):
                        arquivo.write(bloco)
        except httpx.HTTPError as erro:
            # A mensagem não inclui cabeçalho nenhum: o token não pode ir para o log.
            logger.error("[bertimbau] falha ao baixar %s: %s", nome, type(erro).__name__)
            parcial.unlink(missing_ok=True)
            com_problema.append(nome)
            continue

        obtido = sha256_de(parcial)
        if obtido != esperado:
            logger.error(
                "[bertimbau] sha256 de %s nao confere: esperado %s, obtido %s",
                nome,
                esperado,
                obtido,
            )
            parcial.unlink(missing_ok=True)
            com_problema.append(nome)
            continue

        parcial.replace(final)
        logger.info("[bertimbau] ok: %s", nome)

    return com_problema


def main() -> None:
    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    if not settings.bertimbau_repo_hf.strip():
        logger.error(
            "[bertimbau] BERTIMBAU_REPO_HF nao definido: nada a baixar. "
            "O worker vai usar o lexico se a pasta nao tiver o modelo."
        )
        raise SystemExit(1)

    with httpx.Client(timeout=TIMEOUT) as cliente:
        com_problema = baixar(
            settings.caminho_bertimbau,
            settings.bertimbau_repo_hf.strip(),
            settings.bertimbau_revisao_hf.strip() or "main",
            settings.hf_token.strip(),
            cliente,
        )

    if com_problema:
        logger.error(
            "[bertimbau] %s arquivo(s) sem conferir: %s. O worker vai usar o lexico.",
            len(com_problema),
            ", ".join(com_problema),
        )
        raise SystemExit(1)
    logger.info("[bertimbau] pasta completa e conferida: %s", settings.caminho_bertimbau)


if __name__ == "__main__":
    main()
