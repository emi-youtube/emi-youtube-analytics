"""Testes do ensaio de fine-tuning: partição, pesos de classe e `model_card.json`.

**Sem `torch` e sem banco.** O que estes testes protegem é o que decide a qualidade do
treino antes de qualquer GPU: quem entra em cada lado, com que peso, e o que o cartão
promete ao backend. Um teste que exigisse `torch` instalado não rodaria na máquina de
quem só mexe na API — e é justamente essa pessoa que quebra o contrato do cartão sem
perceber.

O laço de treino em si não é testado aqui: ele é exercitado pelo teste de fumaça
(`--limite`), que roda de verdade, contra o modelo de verdade, e está documentado no
README do `ml/treino/`.
"""

import json

import pytest

from ml.config import CLASSES, MAX_LENGTH, MODELO_BASE, SEMENTE
from ml.treino.cartao import CAMPOS_OBRIGATORIOS, montar_cartao, validar_cartao
from ml.treino.dados import (
    Exemplo,
    distribuicao,
    dividir_estratificado,
    pesos_de_classe,
)


def montar_exemplos(por_classe: dict[str, int]) -> list[Exemplo]:
    """Exemplos sintéticos com id crescente, como o banco devolveria."""
    exemplos: list[Exemplo] = []
    identificador = 1
    for classe, quantidade in por_classe.items():
        for _ in range(quantidade):
            exemplos.append(
                Exemplo(
                    id_comentario=identificador,
                    texto=f"comentario {identificador}",
                    texto_modelo=f"comentario {identificador}",
                    rotulo=classe,
                )
            )
            identificador += 1
    return exemplos


# As proporções reais do corpus da Sprint 1 (2.200 de split NULL).
CORPUS = {"positivo": 968, "negativo": 579, "neutro": 653}


# --------------------------------------------------------------------- partição


def test_divide_85_15_e_ninguem_aparece_dos_dois_lados():
    particao = dividir_estratificado(montar_exemplos(CORPUS))

    assert particao.total == 2200
    assert len(particao.treino) == 1870
    assert len(particao.validacao) == 330

    ids_treino = {exemplo.id_comentario for exemplo in particao.treino}
    ids_validacao = {exemplo.id_comentario for exemplo in particao.validacao}
    assert ids_treino & ids_validacao == set()


def test_a_proporcao_das_classes_sobrevive_nos_dois_lados():
    """Sem estratificar, a classe minoritária pode sair rala na validação — e o F1
    macro, que pesa as três igualmente, passaria a depender de poucas dezenas dela."""
    particao = dividir_estratificado(montar_exemplos(CORPUS))

    no_treino = distribuicao(particao.treino)
    na_validacao = distribuicao(particao.validacao)
    for classe, total in CORPUS.items():
        proporcao_original = total / 2200
        assert no_treino[classe] / len(particao.treino) == pytest.approx(
            proporcao_original, abs=0.01
        )
        assert na_validacao[classe] / len(particao.validacao) == pytest.approx(
            proporcao_original, abs=0.02
        )


def test_a_particao_e_a_mesma_em_qualquer_maquina():
    """Comparar dois hiperparâmetros exige que a validação seja a mesma nos dois."""
    primeira = dividir_estratificado(montar_exemplos(CORPUS))
    segunda = dividir_estratificado(montar_exemplos(CORPUS))

    assert [exemplo.id_comentario for exemplo in primeira.validacao] == [
        exemplo.id_comentario for exemplo in segunda.validacao
    ]


def test_semente_diferente_produz_particao_diferente():
    padrao = dividir_estratificado(montar_exemplos(CORPUS))
    outra = dividir_estratificado(montar_exemplos(CORPUS), semente=SEMENTE + 1)

    assert {exemplo.id_comentario for exemplo in padrao.validacao} != {
        exemplo.id_comentario for exemplo in outra.validacao
    }


def test_fracao_invalida_e_recusada():
    with pytest.raises(ValueError, match="entre 0 e 1"):
        dividir_estratificado(montar_exemplos({"positivo": 10}), fracao_validacao=1.5)


# ----------------------------------------------------------------- peso de classe


def test_peso_balanceado_compensa_a_classe_minoritaria():
    """`N / (k * n_j)`, a fórmula do `class_weight='balanced'` (CLAUDE.md regra 8)."""
    pesos = pesos_de_classe(montar_exemplos(CORPUS))
    por_classe = dict(zip(CLASSES, pesos, strict=True))

    assert por_classe["positivo"] == pytest.approx(2200 / (3 * 968))
    assert por_classe["negativo"] == pytest.approx(2200 / (3 * 579))
    assert por_classe["neutro"] == pytest.approx(2200 / (3 * 653))
    # A classe mais rara pesa mais: é o ponto inteiro do balanceamento.
    assert por_classe["negativo"] > por_classe["neutro"] > por_classe["positivo"]


def test_peso_sai_na_ordem_das_classes_do_projeto():
    """Ordem errada daria à classe errada o peso da outra, em silêncio."""
    pesos = pesos_de_classe(montar_exemplos({"positivo": 100, "negativo": 50, "neutro": 50}))
    assert pesos[0] < pesos[1]
    assert pesos[1] == pytest.approx(pesos[2])


def test_corpus_equilibrado_da_peso_1_para_todo_mundo():
    pesos = pesos_de_classe(montar_exemplos({"positivo": 30, "negativo": 30, "neutro": 30}))
    assert pesos == pytest.approx([1.0, 1.0, 1.0])


def test_classe_ausente_no_treino_estoura_em_vez_de_dividir_por_zero():
    with pytest.raises(ValueError, match="nao aparece no treino"):
        pesos_de_classe(montar_exemplos({"positivo": 10, "negativo": 10}))


def test_peso_calculado_so_sobre_o_treino_difere_do_corpus_inteiro():
    """O peso sai do treino, não do corpus: usar tudo deixaria a composição da
    validação vazar para dentro da função de perda."""
    exemplos = montar_exemplos(CORPUS)
    particao = dividir_estratificado(exemplos)

    do_treino = pesos_de_classe(particao.treino)
    do_corpus = pesos_de_classe(exemplos)
    assert do_treino != do_corpus  # parecidos, mas não os mesmos


# -------------------------------------------------------------------- model card


def cartao_de_exemplo(**extras):
    padrao = {
        "classes": CLASSES,
        "max_length": MAX_LENGTH,
        "versao": "0.1.0-ensaio",
        "versao_preprocessamento": "1.1.0",
        "modelo_base": MODELO_BASE,
        "hiperparametros": {"taxa_aprendizado": 3e-5, "epocas": 3},
        "semente": SEMENTE,
        "metricas_validacao": {"f1_macro": 0.8},
        "dados": {"treino": 1870, "validacao": 330},
    }
    padrao.update(extras)
    return montar_cartao(**padrao)


def test_cartao_tem_todos_os_campos_que_o_backend_le():
    cartao = cartao_de_exemplo()
    for campo in CAMPOS_OBRIGATORIOS:
        assert campo in cartao


def test_id2label_preserva_a_ordem_do_projeto():
    """CLAUDE.md regra 5: é daqui que a ordem sai, e hardcodar causa bug silencioso
    (prevê "negativo", grava "neutro")."""
    cartao = cartao_de_exemplo()

    assert cartao["id2label"] == {"0": "positivo", "1": "negativo", "2": "neutro"}
    assert cartao["label2id"] == {"positivo": 0, "negativo": 1, "neutro": 2}


def test_id2label_sobrevive_a_ida_e_volta_pelo_json():
    """JSON não tem chave inteira: quem lê precisa de `int(chave)`, e é o que o
    backend fará. Se isso quebrar, a ordem dos rótulos quebra junto."""
    cartao = json.loads(json.dumps(cartao_de_exemplo()))
    id2label = cartao["id2label"]

    reconstruido = tuple(id2label[str(indice)] for indice in range(len(id2label)))
    assert reconstruido == CLASSES


def test_cartao_carrega_a_versao_do_preprocessamento_instalada():
    """O worker recusa o modelo se divergir da versão dele — e a comparação só
    funciona se o campo estiver preenchido com a versão de verdade."""
    from preprocessamento import VERSAO

    cartao = cartao_de_exemplo(versao_preprocessamento=VERSAO)
    assert cartao["versao_preprocessamento"] == VERSAO


def test_versao_do_modelo_e_do_preprocessamento_sao_campos_diferentes():
    cartao = cartao_de_exemplo(versao="9.9.9", versao_preprocessamento="1.1.0")
    assert cartao["versao"] != cartao["versao_preprocessamento"]


def test_validacao_recusa_cartao_sem_campo_obrigatorio():
    cartao = cartao_de_exemplo()
    del cartao["id2label"]

    with pytest.raises(ValueError, match="id2label"):
        validar_cartao(cartao)


def test_validacao_recusa_id2label_com_buraco():
    cartao = cartao_de_exemplo()
    cartao["id2label"] = {"0": "positivo", "2": "neutro"}

    with pytest.raises(ValueError, match="sem buraco"):
        validar_cartao(cartao)


def test_validacao_recusa_label2id_que_discorda_do_id2label():
    """O par inconsistente é pior que a falta de um dos dois: o backend escolhe um e
    classifica errado sem erro nenhum."""
    cartao = cartao_de_exemplo()
    cartao["label2id"] = {"positivo": 2, "negativo": 1, "neutro": 0}

    with pytest.raises(ValueError, match="discordam"):
        validar_cartao(cartao)


def test_validacao_recusa_max_length_invalido():
    cartao = cartao_de_exemplo(max_length=0)
    with pytest.raises(ValueError, match="max_length"):
        validar_cartao(cartao)


def test_cartao_valido_passa():
    validar_cartao(cartao_de_exemplo())
