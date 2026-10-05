"""Compara dois métodos no teste, pareado: o delta de F1 macro e o IC do bootstrap.

É a conta da regra de decisão da rodada 2 (`ml/treino/historico/regra_decisao_rodada2.md`):
o modelo novo (B) só substitui o de produção (A) se o F1 macro no teste for maior e o
IC 95% do delta pareado não ficar inteiramente abaixo de zero. Serve também para
qualquer outro par — o baseline contra o BERTimbau, por exemplo.

Lê as previsões do mesmo jeito que `avaliar.py` (CSV com `id_comentario` e rótulo) e
o gabarito do mesmo lugar (`rotulo_humano` do banco, ou `--gabarito <csv>`). Não grava
nada no banco.

Uso:
    python -m ml.avaliacao.comparar --id-execucao 4 \\
        --a bertimbau=ml/dados/previsoes_bertimbau.csv \\
        --b bertimbau_rodada2=ml/dados/previsoes_bertimbau_rodada2.csv \\
        --saida ml/treino/historico/comparacao_rodada2.json
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ml.avaliacao.avaliar import ler_csv, ler_do_banco, validar_cobertura
from ml.avaliacao.metricas import (
    CONFIANCA,
    REAMOSTRAGENS,
    SEMENTE,
    DeltaPareado,
    intervalo_bootstrap_pareado,
)
from ml.config import CLASSES

logger = logging.getLogger("comparar")


def decidir_rodada2(delta: DeltaPareado) -> dict[str, Any]:
    """A regra 4 de `regra_decisao_rodada2.md`, escrita como código.

    B substitui A se o F1 macro de B for **maior** e o limite superior do IC do delta
    pareado for ≥ 0 (o intervalo não fica inteiramente abaixo de zero).

    >>> decidir_rodada2(DeltaPareado(0.73, 0.75, 0.02, (-0.01, 0.05), 2000))["substitui"]
    True
    >>> decidir_rodada2(DeltaPareado(0.73, 0.73, 0.0, (-0.02, 0.02), 2000))["substitui"]
    False
    """
    maior = delta.f1_macro_b > delta.f1_macro_a
    ic_nao_todo_negativo = delta.ic[1] >= 0
    return {
        "f1_macro_maior": maior,
        "ic_delta_nao_inteiramente_abaixo_de_zero": ic_nao_todo_negativo,
        "substitui": maior and ic_nao_todo_negativo,
    }


def _carregar(especificacao: str) -> tuple[str, Path]:
    if "=" not in especificacao:
        raise SystemExit(f"esperado nome=caminho.csv, veio {especificacao!r}")
    nome, caminho = especificacao.split("=", 1)
    return nome, Path(caminho)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, default=None)
    parser.add_argument("--gabarito", type=Path, default=None)
    parser.add_argument("--a", required=True, metavar="nome=arquivo.csv", help="referencia")
    parser.add_argument("--b", required=True, metavar="nome=arquivo.csv", help="candidato")
    parser.add_argument("--reamostragens", type=int, default=REAMOSTRAGENS)
    parser.add_argument("--saida", type=Path, default=None, help="JSON com o resultado")
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    problemas = []
    if argumentos.gabarito:
        gabarito, encontrados = ler_csv(argumentos.gabarito, "gabarito")
        problemas += encontrados
    else:
        if argumentos.id_execucao is None:
            raise SystemExit("informe --id-execucao (gabarito do banco) ou --gabarito <csv>")
        do_banco = asyncio.run(ler_do_banco(argumentos.id_execucao, "rotulo_humano"))
        gabarito = {id_comentario: rotulo for id_comentario, rotulo in do_banco.items() if rotulo}

    nome_a, caminho_a = _carregar(argumentos.a)
    nome_b, caminho_b = _carregar(argumentos.b)
    previsoes_a, encontrados = ler_csv(caminho_a, nome_a)
    problemas += encontrados + validar_cobertura(gabarito, previsoes_a, nome_a)
    previsoes_b, encontrados = ler_csv(caminho_b, nome_b)
    problemas += encontrados + validar_cobertura(gabarito, previsoes_b, nome_b)
    if problemas:
        for problema in problemas[:50]:
            logger.error("  %s", problema)
        raise SystemExit(f"VALIDACAO FALHOU - {len(problemas)} problema(s). Nada foi calculado.")

    ids = sorted(gabarito)
    delta = intervalo_bootstrap_pareado(
        [gabarito[i] for i in ids],
        [previsoes_a[i] for i in ids],
        [previsoes_b[i] for i in ids],
        CLASSES,
        reamostragens=argumentos.reamostragens,
    )
    decisao = decidir_rodada2(delta)

    logger.info("")
    logger.info("=" * 70)
    logger.info("COMPARACAO PAREADA - %d comentarios do gabarito humano", len(ids))
    logger.info("=" * 70)
    logger.info("  A (referencia) %-22s F1 macro %.4f", nome_a, delta.f1_macro_a)
    logger.info("  B (candidato)  %-22s F1 macro %.4f", nome_b, delta.f1_macro_b)
    logger.info(
        "  delta B - A: %+.4f   IC %.0f%% pareado [%+.4f; %+.4f]",
        delta.delta,
        100 * CONFIANCA,
        delta.ic[0],
        delta.ic[1],
    )
    logger.info("-" * 70)
    logger.info("  regra da rodada 2: B substitui A? %s", "SIM" if decisao["substitui"] else "NAO")
    logger.info("=" * 70)

    if argumentos.saida:
        argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
        conteudo = {
            "data_utc": datetime.now(UTC).isoformat(),
            "total_avaliado": len(ids),
            "a": {"metodo": nome_a, "origem": str(caminho_a), "f1_macro": delta.f1_macro_a},
            "b": {"metodo": nome_b, "origem": str(caminho_b), "f1_macro": delta.f1_macro_b},
            "delta_b_menos_a": delta.delta,
            "ic95_delta_pareado": list(delta.ic),
            "bootstrap": {
                "reamostragens": delta.reamostragens,
                "confianca": CONFIANCA,
                "semente": SEMENTE,
                "metodo": "percentil pareado",
            },
            "regra_rodada2": decisao,
        }
        argumentos.saida.write_text(
            json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("comparacao -> %s", argumentos.saida)


if __name__ == "__main__":
    main()
