"""A comparação da regra da rodada 2, com dados sintéticos — sem banco.

O cenário que motivou a revisão da regra: o modelo A (rodada 1) viu em treino os
gêmeos de parte do teste e acerta esses de cor; o B (rodada 2) não os viu. Nos 334, A
leva vantagem por memória; nos sem gêmeo, quem lê melhor é B. A regra tem que olhar a
segunda comparação, e reportar a primeira junto.
"""

import csv
import json

import pytest

from ml.avaliacao.comparar import (
    DELTA_MINIMO_ADOCAO,
    decidir_rodada2,
    executar,
    ids_sem_gemeo,
    montar_parser,
)
from ml.avaliacao.metricas import DeltaPareado

CLASSES_CICLO = ("positivo", "negativo", "neutro")

# 90 comentários; os ids 1..15 têm gêmeo no treino.
GABARITO = {i: CLASSES_CICLO[i % 3] for i in range(1, 91)}
COM_GEMEO = set(range(1, 16))


def _errado(rotulo: str) -> str:
    return CLASSES_CICLO[(CLASSES_CICLO.index(rotulo) + 1) % 3]


def _previsoes_a() -> dict[int, str]:
    """A: acerta todos os gêmeos (memória) e erra 1 em cada 5 dos sem gêmeo."""
    return {
        i: rotulo if i in COM_GEMEO or i % 5 else _errado(rotulo) for i, rotulo in GABARITO.items()
    }


def _previsoes_b() -> dict[int, str]:
    """B: erra todos os gêmeos e acerta todos os sem gêmeo."""
    return {i: _errado(rotulo) if i in COM_GEMEO else rotulo for i, rotulo in GABARITO.items()}


def _gravar_csv(caminho, rotulos: dict[int, str]) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(("id_comentario", "previsto"))
        escritor.writerows(sorted(rotulos.items()))


def _gravar_vazamento(caminho, com_gemeo, teste: int = len(GABARITO)) -> None:
    relatorio = {
        "conjuntos": {"teste": teste},
        "teste_x_treino_validacao": {
            "pares": [{"id_comentario": i, "id_gemeo": 1000 + i} for i in sorted(com_gemeo)]
        },
    }
    caminho.write_text(json.dumps(relatorio), encoding="utf-8")


@pytest.fixture
def arquivos(tmp_path):
    _gravar_csv(tmp_path / "gabarito.csv", GABARITO)
    _gravar_csv(tmp_path / "a.csv", _previsoes_a())
    _gravar_csv(tmp_path / "b.csv", _previsoes_b())
    _gravar_vazamento(tmp_path / "vazamento.json", COM_GEMEO)
    return tmp_path


def _argumentos(pasta, *extra: str):
    return montar_parser().parse_args(
        [
            "--gabarito",
            str(pasta / "gabarito.csv"),
            "--a",
            f"rodada1={pasta / 'a.csv'}",
            "--b",
            f"rodada2={pasta / 'b.csv'}",
            "--vazamento",
            str(pasta / "vazamento.json"),
            "--reamostragens",
            "300",
            *extra,
        ]
    )


def test_sem_gemeo_a_principal_e_nos_sem_gemeo_e_a_secundaria_nos_todos(arquivos):
    resultado = executar(_argumentos(arquivos, "--so-sem-gemeo"))

    principal = resultado["comparacao_principal_sem_gemeo"]
    secundaria = resultado["comparacao_secundaria_todos"]
    assert principal["n"] == len(GABARITO) - len(COM_GEMEO)
    assert secundaria["n"] == len(GABARITO)

    # O cenario da revisao: nos todos, a memoria de A pesa; sem gemeo, B le melhor.
    assert principal["f1_macro_b"] == pytest.approx(1.0)
    assert principal["delta_b_menos_a"] > 0
    assert secundaria["delta_b_menos_a"] < principal["delta_b_menos_a"]


def test_sem_gemeo_aplica_a_regra_sobre_a_principal(arquivos):
    resultado = executar(_argumentos(arquivos, "--so-sem-gemeo"))

    regra = resultado["regra_rodada2"]
    principal = resultado["comparacao_principal_sem_gemeo"]
    assert regra["adota"] == (principal["delta_b_menos_a"] >= DELTA_MINIMO_ADOCAO)
    assert regra["adota"]
    assert regra["afirmacao"] == (
        "melhorou" if principal["ic95_delta_pareado"][0] > 0 else "nao distinguivel"
    )


def test_sem_a_flag_a_regra_nao_e_aplicada(arquivos):
    resultado = executar(_argumentos(arquivos))

    assert "regra_rodada2" not in resultado
    assert "comparacao_principal_sem_gemeo" not in resultado
    assert resultado["comparacao_todos"]["n"] == len(GABARITO)


def test_relatorio_de_vazamento_de_outro_teste_e_recusado(tmp_path):
    with pytest.raises(SystemExit, match="outro teste"):
        _gravar_vazamento(tmp_path / "v.json", {999})
        ids_sem_gemeo(tmp_path / "v.json", GABARITO)

    with pytest.raises(SystemExit, match="rode o vazamento de novo"):
        _gravar_vazamento(tmp_path / "v.json", COM_GEMEO, teste=334)
        ids_sem_gemeo(tmp_path / "v.json", GABARITO)


def test_ids_sem_gemeo_e_o_complemento_dos_pares(tmp_path):
    _gravar_vazamento(tmp_path / "v.json", COM_GEMEO)
    assert ids_sem_gemeo(tmp_path / "v.json", GABARITO) == set(GABARITO) - COM_GEMEO


@pytest.mark.parametrize(
    ("delta", "ic", "adota", "afirmacao"),
    [
        (0.010, (-0.02, 0.04), True, "nao distinguivel"),  # no limite: adota
        (0.0099, (-0.02, 0.04), False, "nao distinguivel"),
        (0.030, (0.005, 0.06), True, "melhorou"),
        (0.008, (0.001, 0.02), False, "melhorou"),  # distinguivel, mas pequeno demais
        (-0.020, (-0.05, 0.01), False, "nao distinguivel"),
    ],
)
def test_decidir_rodada2_separa_adocao_de_afirmacao(delta, ic, adota, afirmacao):
    """Adotar e afirmar são perguntas diferentes: um delta de +0,008 com IC acima de
    zero é uma melhora real e pequena demais para trocar o modelo de produção."""
    regra = decidir_rodada2(DeltaPareado(0.70, 0.70 + delta, delta, ic, 2000))

    assert regra["adota"] is adota
    assert regra["afirmacao"] == afirmacao
