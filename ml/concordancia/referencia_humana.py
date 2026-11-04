"""Referência do nível humano para ler o F1 do modelo (Seção 5.2.2 do TCC).

Para cada avaliador, toma os comentários em que os OUTROS dois concordam e mede o
avaliador contra esse consenso. É a régua de quanto uma pessoa acerta quando o caso é
claro o bastante para dois colegas concordarem. O modelo é medido nos MESMOS
comentários e contra o mesmo consenso, e as duas médias saem lado a lado.

**Por que os dois números ficam acima do F1 do teste inteiro.** A conta usa só os
comentários em que dois avaliadores concordam, que são os menos ambíguos. A razão
entre as médias (modelo / humano) é a leitura que interessa: quanto do nível humano o
modelo alcança nos casos claros.

Entradas, ambas fora do git: as planilhas dos avaliadores
(`ml/amostra/respostas/avaliador_{1,2,3}.xlsx`) e as previsões do modelo
(`ml/dados/previsoes_bertimbau.csv`, colunas `id_comentario` e `previsto`). A saída só
tem números, nenhum texto de comentário:

    python -m ml.concordancia.referencia_humana
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ml.avaliacao.avaliar import ler_csv
from ml.avaliacao.metricas import avaliar_previsoes
from ml.concordancia.calcular_concordancia import AVALIADORES, DIRETORIO_RESPOSTAS, ler_planilha
from ml.concordancia.kappa import kappa_cohen
from ml.config import CLASSES, DIRETORIO_ML

PREVISOES_PADRAO = DIRETORIO_ML / "dados" / "previsoes_bertimbau.csv"
SAIDA_PADRAO = DIRETORIO_ML / "concordancia" / "resultado_referencia_humana.json"


def referencia(rotulos: dict[str, dict[int, str]], previsoes: dict[int, str]) -> dict[str, object]:
    """Mede cada avaliador e o modelo contra o consenso dos outros dois avaliadores.

    `rotulos` é {avaliador: {id_comentario: rotulo}}; os três avaliadores precisam ter
    rotulado os mesmos comentários, e o modelo precisa ter previsto todos eles.
    """
    nomes = sorted(rotulos)
    if len(nomes) != 3:
        raise ValueError(f"a referência pede exatamente 3 avaliadores, vieram {len(nomes)}")
    ids = sorted(rotulos[nomes[0]])
    for nome in nomes[1:]:
        if sorted(rotulos[nome]) != ids:
            raise ValueError(f"{nome} não rotulou os mesmos comentários que {nomes[0]}")
    faltando = [i for i in ids if i not in previsoes]
    if faltando:
        raise ValueError(f"o modelo não previu {len(faltando)} comentários (ex.: {faltando[:5]})")

    por_avaliador = []
    for nome in nomes:
        outros = [rotulos[o] for o in nomes if o != nome]
        consenso_ids = [i for i in ids if outros[0][i] == outros[1][i]]
        consenso = [outros[0][i] for i in consenso_ids]
        humano = [rotulos[nome][i] for i in consenso_ids]
        modelo = [previsoes[i] for i in consenso_ids]
        por_avaliador.append(
            {
                "avaliador": nome,
                "comentarios_com_consenso_dos_outros_dois": len(consenso_ids),
                "humano": {
                    "f1_macro": avaliar_previsoes(consenso, humano, CLASSES).f1_macro,
                    "kappa_cohen": kappa_cohen(consenso, humano),
                },
                "modelo": {
                    "f1_macro": avaliar_previsoes(consenso, modelo, CLASSES).f1_macro,
                    "kappa_cohen": kappa_cohen(consenso, modelo),
                },
            }
        )

    def media(quem: str, medida: str) -> float:
        return sum(a[quem][medida] for a in por_avaliador) / len(por_avaliador)

    humano_f1 = media("humano", "f1_macro")
    modelo_f1 = media("modelo", "f1_macro")
    return {
        "total_comentarios": len(ids),
        "por_avaliador": por_avaliador,
        "media": {
            "humano_f1_macro": humano_f1,
            "humano_kappa_cohen": media("humano", "kappa_cohen"),
            "modelo_f1_macro": modelo_f1,
            "modelo_kappa_cohen": media("modelo", "kappa_cohen"),
            "razao_f1_modelo_sobre_humano": modelo_f1 / humano_f1,
        },
    }


def ler_avaliadores(diretorio: Path) -> dict[str, dict[int, str]]:
    rotulos: dict[str, dict[int, str]] = {}
    for nome in AVALIADORES:
        respostas, problemas = ler_planilha(diretorio / f"{nome}.xlsx", nome, normalizar=True)
        erros = [p for p in problemas if not p.descricao.startswith("NORMALIZADO")]
        if erros:
            raise SystemExit("\n".join(str(p) for p in erros))
        rotulos[nome] = {r.id_comentario: r.rotulo for r in respostas}
    return rotulos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--respostas", type=Path, default=DIRETORIO_RESPOSTAS)
    parser.add_argument("--previsoes", type=Path, default=PREVISOES_PADRAO)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    argumentos = parser.parse_args(argv)

    previsoes, problemas = ler_csv(argumentos.previsoes, "modelo")
    if problemas:
        raise SystemExit("\n".join(str(p) for p in problemas))
    resultado = referencia(ler_avaliadores(argumentos.respostas), previsoes)
    resultado = {
        "data_utc": datetime.now(UTC).isoformat(),
        "aviso": "so numeros: nenhum texto de comentario",
        "previsoes": argumentos.previsoes.name,
        "criterio": "cada avaliador e o modelo contra o consenso dos outros dois avaliadores, "
        "nos comentarios em que esses dois concordam; F1 macro com denominador 3",
        **resultado,
    }
    argumentos.saida.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    media = resultado["media"]
    print(
        f"humano F1 {media['humano_f1_macro']:.3f} (kappa {media['humano_kappa_cohen']:.2f}) | "
        f"modelo F1 {media['modelo_f1_macro']:.3f} (kappa {media['modelo_kappa_cohen']:.2f}) | "
        f"razao {media['razao_f1_modelo_sobre_humano']:.1%}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
