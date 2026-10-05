"""Compara dois métodos no teste, pareado: o delta de F1 macro e o IC do bootstrap.

É a conta da regra de decisão da rodada 2 (`ml/treino/historico/regra_decisao_rodada2.md`,
seção "Revisão"). Serve também para qualquer outro par — o baseline contra o
BERTimbau, por exemplo.

**`--so-sem-gemeo` é a comparação da regra.** A rodada 1 treinou com os gêmeos de 25
comentários do teste; a rodada 2 os removeu antes de treinar. Nos 334, a comparação
favorece a rodada 1 por memória, não por leitura. Com a flag, a comparação PRINCIPAL é
nos comentários do teste sem gêmeo no treino+validação (os ids saem de
`ml/avaliacao/saida_vazamento/resultado_vazamento.json`), e os 334 entram como
comparação SECUNDÁRIA, reportada junto. A regra só é aplicada com a flag.

A regra (revisada em 04/10/2026, antes de qualquer treino da rodada 2):

- **adotar em produção**: B substitui A se o delta pontual da comparação principal for
  ≥ +0,010 — aproximadamente o desvio entre sementes na validação (0,011);
- **afirmação científica**: "B melhorou" só se o limite inferior do IC 95% do delta
  for > 0; senão, "não distinguível".

Lê as previsões do mesmo jeito que `avaliar.py` (CSV com `id_comentario` e rótulo) e
o gabarito do mesmo lugar (`rotulo_humano` do banco, ou `--gabarito <csv>`). Não grava
nada no banco.

Uso:
    python -m ml.avaliacao.comparar --id-execucao 4 --so-sem-gemeo \\
        --a bertimbau=ml/dados/previsoes_bertimbau.csv \\
        --b bertimbau_rodada2=ml/dados/previsoes_bertimbau_rodada2.csv \\
        --saida ml/treino/historico/comparacao_rodada2.json
"""

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ml.avaliacao.avaliar import Problema, ler_csv, ler_do_banco, validar_cobertura
from ml.avaliacao.metricas import (
    CONFIANCA,
    REAMOSTRAGENS,
    SEMENTE,
    DeltaPareado,
    intervalo_bootstrap_pareado,
)
from ml.config import CLASSES, DIRETORIO_ML

logger = logging.getLogger("comparar")

ARQUIVO_VAZAMENTO = DIRETORIO_ML / "avaliacao" / "saida_vazamento" / "resultado_vazamento.json"

# Delta mínimo para adotar o modelo novo em produção: aproximadamente o desvio padrão
# do F1 macro de validação entre as cinco sementes da rodada 1 (0,011). Abaixo disso,
# a diferença é do tamanho do que a semente sozinha já muda.
DELTA_MINIMO_ADOCAO = 0.010


def ids_sem_gemeo(caminho: Path, gabarito: Iterable[int]) -> set[int]:
    """Os ids do gabarito que NÃO têm gêmeo no treino+validação.

    Os pares com gêmeo vêm de `teste_x_treino_validacao.pares` do relatório de
    vazamento. Confere que o relatório fala deste teste: se algum id com gêmeo não
    estiver no gabarito, ou se o tamanho do teste divergir, o relatório é de outro
    corpus e a comparação seria feita no subconjunto errado — isso é erro, não aviso.
    """
    if not caminho.exists():
        raise SystemExit(f"{caminho} nao existe: rode antes `python -m ml.avaliacao.vazamento`.")
    relatorio = json.loads(caminho.read_text(encoding="utf-8"))
    com_gemeo = {par["id_comentario"] for par in relatorio["teste_x_treino_validacao"]["pares"]}
    ids = set(gabarito)

    fora = com_gemeo - ids
    if fora:
        raise SystemExit(
            f"{len(fora)} id(s) com gemeo no relatorio de vazamento nao estao no gabarito "
            f"(ex.: {sorted(fora)[:5]}): o relatorio e de outro teste."
        )
    teste = relatorio.get("conjuntos", {}).get("teste")
    if teste is not None and teste != len(ids):
        raise SystemExit(
            f"o relatorio de vazamento descreve {teste} comentarios de teste e o gabarito "
            f"tem {len(ids)}: rode o vazamento de novo."
        )
    return ids - com_gemeo


def comparar(
    gabarito: dict[int, str],
    previsoes_a: dict[int, str],
    previsoes_b: dict[int, str],
    ids: Iterable[int],
    reamostragens: int = REAMOSTRAGENS,
) -> DeltaPareado:
    """Delta pareado B - A nos `ids` dados, na ordem de id."""
    ordem = sorted(ids)
    return intervalo_bootstrap_pareado(
        [gabarito[i] for i in ordem],
        [previsoes_a[i] for i in ordem],
        [previsoes_b[i] for i in ordem],
        CLASSES,
        reamostragens=reamostragens,
    )


def decidir_rodada2(principal: DeltaPareado) -> dict[str, Any]:
    """A regra revisada, escrita como código. Recebe a comparação PRINCIPAL (sem gêmeo).

    >>> decidir_rodada2(DeltaPareado(0.72, 0.735, 0.015, (-0.01, 0.04), 2000))["adota"]
    True
    >>> decidir_rodada2(DeltaPareado(0.72, 0.735, 0.015, (-0.01, 0.04), 2000))["afirmacao"]
    'nao distinguivel'
    >>> decidir_rodada2(DeltaPareado(0.72, 0.728, 0.008, (0.001, 0.02), 2000))["adota"]
    False
    """
    adota = principal.delta >= DELTA_MINIMO_ADOCAO
    melhorou = principal.ic[0] > 0
    return {
        "criterio_adocao": f"delta pontual da comparacao principal >= {DELTA_MINIMO_ADOCAO}",
        "adota": adota,
        "criterio_afirmacao": "limite inferior do IC 95% do delta > 0",
        "afirmacao": "melhorou" if melhorou else "nao distinguivel",
    }


def _resumo(delta: DeltaPareado, n: int) -> dict[str, Any]:
    return {
        "n": n,
        "f1_macro_a": delta.f1_macro_a,
        "f1_macro_b": delta.f1_macro_b,
        "delta_b_menos_a": delta.delta,
        "ic95_delta_pareado": list(delta.ic),
    }


def _especificacao(texto: str) -> tuple[str, Path]:
    if "=" not in texto:
        raise SystemExit(f"esperado nome=caminho.csv, veio {texto!r}")
    nome, caminho = texto.split("=", 1)
    return nome, Path(caminho)


def executar(argumentos: argparse.Namespace) -> dict[str, Any]:
    """Carrega, valida e compara. Devolve o resultado inteiro (é o que vai para o JSON)."""
    problemas: list[Problema] = []
    if argumentos.gabarito:
        gabarito, encontrados = ler_csv(argumentos.gabarito, "gabarito")
        problemas += encontrados
    else:
        if argumentos.id_execucao is None:
            raise SystemExit("informe --id-execucao (gabarito do banco) ou --gabarito <csv>")
        do_banco = asyncio.run(ler_do_banco(argumentos.id_execucao, "rotulo_humano"))
        gabarito = {id_comentario: rotulo for id_comentario, rotulo in do_banco.items() if rotulo}

    nome_a, caminho_a = _especificacao(argumentos.a)
    nome_b, caminho_b = _especificacao(argumentos.b)
    previsoes_a, encontrados = ler_csv(caminho_a, nome_a)
    problemas += encontrados + validar_cobertura(gabarito, previsoes_a, nome_a)
    previsoes_b, encontrados = ler_csv(caminho_b, nome_b)
    problemas += encontrados + validar_cobertura(gabarito, previsoes_b, nome_b)
    if problemas:
        for problema in problemas[:50]:
            logger.error("  %s", problema)
        raise SystemExit(f"VALIDACAO FALHOU - {len(problemas)} problema(s). Nada foi calculado.")

    todos = comparar(gabarito, previsoes_a, previsoes_b, gabarito, argumentos.reamostragens)
    resultado: dict[str, Any] = {
        "data_utc": datetime.now(UTC).isoformat(),
        "a": {"metodo": nome_a, "origem": caminho_a.name},
        "b": {"metodo": nome_b, "origem": caminho_b.name},
        "bootstrap": {
            "reamostragens": argumentos.reamostragens,
            "confianca": CONFIANCA,
            "semente": SEMENTE,
            "metodo": "percentil pareado",
        },
    }

    if not argumentos.so_sem_gemeo:
        resultado["comparacao_todos"] = _resumo(todos, len(gabarito))
        return resultado

    sem_gemeo = ids_sem_gemeo(argumentos.vazamento, gabarito)
    principal = comparar(gabarito, previsoes_a, previsoes_b, sem_gemeo, argumentos.reamostragens)
    resultado["comparacao_principal_sem_gemeo"] = {
        **_resumo(principal, len(sem_gemeo)),
        "fonte_dos_ids": f"{argumentos.vazamento.name}: teste sem gemeo no treino+validacao",
    }
    resultado["comparacao_secundaria_todos"] = _resumo(todos, len(gabarito))
    resultado["regra_rodada2"] = decidir_rodada2(principal)
    return resultado


def _relatar_comparacao(titulo: str, bloco: dict[str, Any], nome_a: str, nome_b: str) -> None:
    logger.info("  %s - %d comentarios", titulo, bloco["n"])
    logger.info("    A %-22s F1 macro %.4f", nome_a, bloco["f1_macro_a"])
    logger.info("    B %-22s F1 macro %.4f", nome_b, bloco["f1_macro_b"])
    ic = bloco["ic95_delta_pareado"]
    logger.info(
        "    delta B - A: %+.4f   IC %.0f%% pareado [%+.4f; %+.4f]",
        bloco["delta_b_menos_a"],
        100 * CONFIANCA,
        ic[0],
        ic[1],
    )


def relatar(resultado: dict[str, Any]) -> None:
    nome_a, nome_b = resultado["a"]["metodo"], resultado["b"]["metodo"]
    logger.info("")
    logger.info("=" * 70)
    logger.info("COMPARACAO PAREADA - gabarito humano")
    logger.info("=" * 70)
    if "comparacao_principal_sem_gemeo" not in resultado:
        _relatar_comparacao("todos", resultado["comparacao_todos"], nome_a, nome_b)
        logger.info("-" * 70)
        logger.info("  regra da rodada 2 NAO aplicada: ela exige --so-sem-gemeo")
        logger.info("=" * 70)
        return

    _relatar_comparacao(
        "PRINCIPAL: sem gemeo", resultado["comparacao_principal_sem_gemeo"], nome_a, nome_b
    )
    logger.info("")
    _relatar_comparacao(
        "secundaria: todos", resultado["comparacao_secundaria_todos"], nome_a, nome_b
    )
    regra = resultado["regra_rodada2"]
    logger.info("-" * 70)
    logger.info("  regra da rodada 2 (sobre a comparacao principal):")
    logger.info(
        "    adotar %s em producao? %s  (%s)",
        nome_b,
        "SIM" if regra["adota"] else "NAO - fica " + nome_a,
        regra["criterio_adocao"],
    )
    logger.info(
        "    afirmacao no TCC: %s  (%s)",
        regra["afirmacao"].upper(),
        regra["criterio_afirmacao"],
    )
    logger.info("=" * 70)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, default=None)
    parser.add_argument("--gabarito", type=Path, default=None)
    parser.add_argument("--a", required=True, metavar="nome=arquivo.csv", help="referencia")
    parser.add_argument("--b", required=True, metavar="nome=arquivo.csv", help="candidato")
    parser.add_argument(
        "--so-sem-gemeo",
        action="store_true",
        help=(
            "comparacao principal so nos comentarios sem gemeo no treino+validacao, "
            "os 334 como secundaria, e aplica a regra da rodada 2"
        ),
    )
    parser.add_argument(
        "--vazamento",
        type=Path,
        default=ARQUIVO_VAZAMENTO,
        help="resultado_vazamento.json de onde saem os ids com gemeo",
    )
    parser.add_argument("--reamostragens", type=int, default=REAMOSTRAGENS)
    parser.add_argument("--saida", type=Path, default=None, help="JSON com o resultado")
    return parser


def main() -> None:
    argumentos = montar_parser().parse_args()
    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    resultado = executar(argumentos)
    relatar(resultado)

    if argumentos.saida:
        argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
        argumentos.saida.write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("comparacao -> %s", argumentos.saida)


if __name__ == "__main__":
    main()
