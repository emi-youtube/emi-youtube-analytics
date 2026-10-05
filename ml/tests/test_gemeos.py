"""Gêmeos, o filtro de vazamento da rodada 2 e o bootstrap pareado.

Sem banco e sem `torch`: o critério de gêmeo é stdlib pura (roda no Colab sem pacote
novo), e é ele que decide quais exemplos a rodada 2 deixa de ver. Um erro aqui muda o
treino em silêncio — removendo demais, ou deixando o vazamento passar.
"""

import pytest

from ml.avaliacao.gemeos import (
    LIMIAR_QUASE,
    NIVEL_EXATO,
    NIVEL_QUASE,
    buscar_gemeos,
    jaccard,
    ngramas,
    normalizar,
)
from ml.avaliacao.metricas import avaliar_previsoes, intervalo_bootstrap_pareado
from ml.config import CLASSES
from ml.treino.dados import Exemplo, Particao, remover_vazamento

# ------------------------------------------------------------------ normalizar


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Coisa linda", "COISA LINDA"),
        ("Mídia física", "midia fisica"),
        ("VAMOOOO!!", "vamo"),
        ("eita!", "Eita"),
        ("Yeah Yeah Yeahs - Spitting", "yeah yeah yeahs spitting"),
    ],
)
def test_normalizar_iguala_o_que_o_enunciado_manda_igualar(a, b):
    """Minúsculas, sem acento, sem pontuação, letra repetida reduzida."""
    assert normalizar(a) == normalizar(b)


def test_normalizar_nao_iguala_palavras_diferentes():
    assert normalizar("A TIM é melhor") != normalizar("A TIM é muito melhor")


def test_texto_so_de_pontuacao_normaliza_para_vazio_e_nao_tem_gemeo():
    """Vazio com vazio não é gêmeo: não há texto para o modelo ter decorado."""
    assert normalizar("!!! ...") == ""
    assert buscar_gemeos([(1, "!!!")], [(2, "...")]) == {}


# --------------------------------------------------------------------- jaccard


def test_jaccard_de_iguais_e_um_e_de_disjuntos_e_zero():
    assert jaccard(ngramas("abc"), ngramas("abc")) == 1.0
    assert jaccard(ngramas("abc"), ngramas("xyz")) == 0.0
    assert jaccard(frozenset(), ngramas("abc")) == 0.0


# --------------------------------------------------------------- buscar_gemeos


def test_exato_vence_quase():
    gemeos = buscar_gemeos(
        [(1, "Que carro lindo")],
        [(5, "que carro lindo demais"), (9, "QUE CARRO LINDO!")],
    )
    assert gemeos[1].nivel == NIVEL_EXATO
    assert gemeos[1].id_gemeo == 9


def test_quase_acima_do_limiar_e_gemeo_abaixo_nao():
    """Os pares do corpus que fundamentam o limiar (docstring de `gemeos.py`)."""
    acima = buscar_gemeos([(1, "que musica maravilhosa")], [(2, "Música maravilhosa")])
    abaixo = buscar_gemeos(
        [(1, "Como é o nome da música e quem canta?")], [(2, "Como é o nome da musica ?")]
    )
    assert acima[1].nivel == NIVEL_QUASE
    assert acima[1].similaridade >= LIMIAR_QUASE
    assert abaixo == {}


def test_o_mesmo_id_nao_e_gemeo_de_si_mesmo():
    """É o que permite procurar gêmeos de um conjunto dentro dele mesmo."""
    treino = [(1, "Parabéns"), (2, "parabens!"), (3, "outra coisa")]
    gemeos = buscar_gemeos(treino, treino)

    assert set(gemeos) == {1, 2}
    assert gemeos[1].id_gemeo == 2
    assert gemeos[2].id_gemeo == 1


def test_empate_vai_para_o_menor_id():
    gemeos = buscar_gemeos([(1, "top")], [(30, "TOP"), (20, "top"), (25, "Top!")])
    assert gemeos[1].id_gemeo == 20


def test_limiar_fora_do_intervalo_e_recusado():
    with pytest.raises(ValueError):
        buscar_gemeos([(1, "a")], [(2, "a")], limiar=0)


def test_a_poda_por_tamanho_nao_perde_par_nenhum():
    """A poda é uma otimização: o resultado tem que ser o da força bruta."""
    textos = [
        (1, "Que carro lindo"),
        (2, "que carro lindo demais"),
        (3, "Música maravilhosa"),
        (4, "que musica maravilhosa"),
        (5, "Lindo"),
        (6, "Lindo lindo lindo"),
        (7, "Vocês só tem UM trabalho, SÓ UM."),
        (8, "Ubi, vocês só tem UM trabalho...."),
    ]
    gemeos = buscar_gemeos(textos, textos)

    for id_a, texto_a in textos:
        melhor = max(
            (
                jaccard(ngramas(normalizar(texto_a)), ngramas(normalizar(texto_b)))
                for id_b, texto_b in textos
                if id_b != id_a
            ),
            default=0.0,
        )
        assert (id_a in gemeos) == (melhor >= LIMIAR_QUASE), id_a


# ------------------------------------------------------- o filtro da rodada 2


def _exemplo(identificador: int, texto: str, rotulo: str = "positivo") -> Exemplo:
    return Exemplo(identificador, texto, texto, rotulo)


def test_remover_vazamento_tira_os_gemeos_do_teste_dos_dois_lados():
    particao = Particao(
        treino=[_exemplo(1, "Comprei um Nivus e deu falha"), _exemplo(2, "adorei")],
        validacao=[_exemplo(3, "galinha caipira"), _exemplo(4, "nada a ver")],
    )
    # O teste chega SEM rotulo, como `carregar_teste` entrega.
    teste = [_exemplo(10, "comprei um nivus e deu falha!", ""), _exemplo(11, "Galinha caipira", "")]

    filtrada, filtro = remover_vazamento(particao, teste)

    assert [e.id_comentario for e in filtrada.treino] == [2]
    assert [e.id_comentario for e in filtrada.validacao] == [4]
    assert filtro.gemeo_teste_no_treino == (1,)
    assert filtro.gemeo_teste_na_validacao == (3,)
    assert filtro.gemeo_validacao_no_treino == ()


def test_remover_vazamento_tira_do_treino_a_duplicidade_com_a_validacao():
    """A validação escolhe a configuração: ela não pode medir memória do treino."""
    particao = Particao(
        treino=[_exemplo(1, "Vim pela música"), _exemplo(2, "adorei")],
        validacao=[_exemplo(3, "vim pela musica."), _exemplo(4, "nada a ver")],
    )

    filtrada, filtro = remover_vazamento(particao, teste=[])

    assert [e.id_comentario for e in filtrada.treino] == [2]
    assert [e.id_comentario for e in filtrada.validacao] == [3, 4]
    assert filtro.gemeo_validacao_no_treino == (1,)


def test_o_relatorio_do_filtro_tem_contagens_e_ids_e_nenhum_texto():
    particao = Particao(treino=[_exemplo(1, "segredo do comentario")], validacao=[])
    _, filtro = remover_vazamento(particao, [_exemplo(9, "Segredo do comentário", "")])

    relatorio = filtro.como_dicionario()
    assert relatorio["removidos"]["treino_com_gemeo_no_teste"] == 1
    assert relatorio["ids_removidos"]["treino_com_gemeo_no_teste"] == [1]
    assert "segredo" not in str(relatorio).lower()


# --------------------------------------------------------- bootstrap pareado


VERDADEIROS = ["positivo", "negativo", "neutro"] * 20
QUASE_CERTO = ["positivo", "negativo", "neutro"] * 18 + ["neutro", "neutro", "positivo"] * 2


def test_delta_de_um_metodo_contra_ele_mesmo_e_zero_com_ic_zero():
    delta = intervalo_bootstrap_pareado(
        VERDADEIROS, QUASE_CERTO, QUASE_CERTO, CLASSES, reamostragens=200
    )
    assert delta.delta == 0
    assert delta.ic == (0.0, 0.0)


def test_delta_pontual_e_a_diferenca_dos_f1_macro():
    piso = ["positivo"] * len(VERDADEIROS)
    delta = intervalo_bootstrap_pareado(VERDADEIROS, piso, QUASE_CERTO, CLASSES, reamostragens=200)

    esperado = (
        avaliar_previsoes(VERDADEIROS, QUASE_CERTO, CLASSES).f1_macro
        - avaliar_previsoes(VERDADEIROS, piso, CLASSES).f1_macro
    )
    assert delta.delta == pytest.approx(esperado)
    assert delta.ic[0] <= delta.delta <= delta.ic[1]
    assert delta.ic[0] > 0  # um metodo bom contra o chute de uma classe so


def test_bootstrap_pareado_e_deterministico():
    piso = ["positivo"] * len(VERDADEIROS)
    um = intervalo_bootstrap_pareado(VERDADEIROS, piso, QUASE_CERTO, CLASSES, reamostragens=100)
    dois = intervalo_bootstrap_pareado(VERDADEIROS, piso, QUASE_CERTO, CLASSES, reamostragens=100)
    assert um == dois
