"""Testes da análise de sensibilidade e da referência humana (Capítulo 5).

Nada aqui toca o banco nem as planilhas reais: os dados são sintéticos, montados para
que a resposta certa seja conhecida de antemão.
"""

import pytest

from ml.avaliacao.metricas import avaliar_previsoes
from ml.avaliacao.sensibilidade import (
    GEMINI,
    analisar,
    bootstrap_por_video,
    matriz_ponderada,
    metricas_da_matriz,
    sem_descartados,
)
from ml.concordancia.kappa import kappa_cohen
from ml.concordancia.referencia_humana import referencia
from ml.config import CLASSES

ROTULOS = list(CLASSES)


def _exemplo(i, video, fraco, humano, split="teste"):
    return {
        "id_comentario": str(i),
        "id_video": str(video),
        "rotulo_fraco": fraco,
        "rotulo_humano": humano if split == "teste" else "",
        "split": split,
    }


def _conjunto():
    """30 de teste (10 por estrato, 3 vídeos) e 60 de treino, todos com rótulo fraco."""
    exemplos, i = [], 0
    for estrato in ROTULOS:
        for k in range(10):
            humano = estrato if k < 8 else ROTULOS[(ROTULOS.index(estrato) + 1) % 3]
            exemplos.append(_exemplo(i, k % 3, estrato, humano))
            i += 1
    for estrato, quantos in zip(ROTULOS, (30, 20, 10), strict=True):
        for _ in range(quantos):
            exemplos.append(_exemplo(i, 9, estrato, None, split="treino"))
            i += 1
    return exemplos


def test_matriz_com_pesos_iguais_reproduz_as_metricas_sem_peso():
    verdadeiros = ["positivo", "negativo", "neutro", "neutro", "positivo", "negativo"]
    previstos = ["positivo", "neutro", "neutro", "positivo", "positivo", "negativo"]
    sem_peso = avaliar_previsoes(verdadeiros, previstos, CLASSES)
    com_peso = metricas_da_matriz(matriz_ponderada(verdadeiros, previstos, [2.5] * 6))
    assert com_peso["f1_macro"] == pytest.approx(sem_peso.f1_macro)
    assert com_peso["acuracia"] == pytest.approx(sem_peso.acuracia)
    assert com_peso["kappa_cohen"] == pytest.approx(kappa_cohen(verdadeiros, previstos))


def test_ponderacao_devolve_a_proporcao_do_corpus():
    exemplos = _conjunto()
    teste = [e for e in exemplos if e["split"] == "teste"]
    previsoes = {"perfeito": {int(t["id_comentario"]): t["rotulo_humano"] for t in teste}}
    resultado = analisar(exemplos, previsoes, set(), reamostragens=50)

    # o corpus inteiro: 40 positivos, 30 negativos e 20 neutros pelo rótulo fraco
    assert resultado["populacao_por_rotulo_fraco"] == {"positivo": 40, "negativo": 30, "neutro": 20}
    perfeito = resultado["ponderado_pelos_estratos"]["perfeito"]
    assert perfeito["f1_macro"] == pytest.approx(1.0)
    assert perfeito["ic95_f1_macro"] == [pytest.approx(1.0), pytest.approx(1.0)]
    # a Gemini (rótulo fraco) entra sozinha e erra 2 de cada 10 em cada estrato
    gemini = resultado["como_publicado"][GEMINI]
    assert gemini["acuracia"] == pytest.approx(0.8)
    assert resultado["ponderado_pelos_estratos"][GEMINI]["acuracia"] == pytest.approx(0.8)


def test_bootstrap_por_video_sorteia_videos_inteiros():
    teste = [e for e in _conjunto() if e["split"] == "teste"]
    perfeito = {int(t["id_comentario"]): t["rotulo_humano"] for t in teste}
    resultado = bootstrap_por_video(teste, {"perfeito": perfeito}, reamostragens=30)
    assert resultado["videos"] == 3
    assert sum(resultado["comentarios_por_video"].values()) == 30
    assert resultado["ic95_f1_macro"]["perfeito"] == [pytest.approx(1.0), pytest.approx(1.0)]


def test_sem_descartados_tira_so_os_ids_pedidos():
    teste = [e for e in _conjunto() if e["split"] == "teste"]
    perfeito = {int(t["id_comentario"]): t["rotulo_humano"] for t in teste}
    resultado = sem_descartados(teste, {"perfeito": perfeito}, {0, 1, 2})
    assert resultado["n"] == 27 and resultado["descartados"] == 3
    assert resultado["perfeito"]["f1_macro"] == pytest.approx(1.0)


def test_metodo_sem_previsao_para_todo_o_teste_e_recusado():
    exemplos = _conjunto()
    with pytest.raises(SystemExit):
        analisar(exemplos, {"incompleto": {0: "positivo"}}, set(), reamostragens=5)


def test_referencia_humana_mede_cada_um_contra_os_outros_dois():
    ids = range(9)
    base = {i: ROTULOS[i % 3] for i in ids}
    discordante = dict(base)
    discordante[0] = "negativo"  # o avaliador_3 erra um comentário
    rotulos = {"avaliador_1": base, "avaliador_2": dict(base), "avaliador_3": discordante}
    resultado = referencia(rotulos, previsoes=dict(base))

    por_nome = {a["avaliador"]: a for a in resultado["por_avaliador"]}
    # contra o consenso de 1 e 2 (que concordam em tudo), o avaliador_3 erra 1 de 9
    assert por_nome["avaliador_3"]["comentarios_com_consenso_dos_outros_dois"] == 9
    assert por_nome["avaliador_3"]["humano"]["f1_macro"] < 1.0
    # para os outros dois, o comentário 0 sai do consenso (1 ou 2 x 3 discordam)
    assert por_nome["avaliador_1"]["comentarios_com_consenso_dos_outros_dois"] == 8
    assert por_nome["avaliador_1"]["modelo"]["f1_macro"] == pytest.approx(1.0)


def test_referencia_recusa_modelo_que_nao_previu_tudo():
    base = {i: ROTULOS[i % 3] for i in range(6)}
    rotulos = {"a": base, "b": dict(base), "c": dict(base)}
    with pytest.raises(ValueError):
        referencia(rotulos, previsoes={0: "positivo"})
