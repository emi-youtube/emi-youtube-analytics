"""O treino oficial com cinco sementes: a estatística e a escolha de quem é publicado.

Separado de `test_treino.py` por causa de uma dependência: estas funções moram em
`ml/treino/treinar.py`, que importa `torch` no topo. O `test_treino.py` é justamente o
arquivo que roda **sem** `torch`, para que quem só mexe na API consiga rodá-lo — e é
essa pessoa que quebra o contrato do `model_card.json` sem perceber. Em vez de arrastar
o `torch` para lá, o que depende dele fica aqui, e aqui o teste se pula sozinho quando
o `torch` não está instalado.

O que estes testes protegem é o que a banca vai perguntar: de onde saem a média e o
desvio, e por que o modelo publicado é o da semente mediana e não o da melhor.
"""

import json

import pytest

torch = pytest.importorskip("torch", reason="pip install -r ml/requirements-treino.txt")

from ml.config import SEMENTE  # noqa: E402
from ml.treino.treinar import (  # noqa: E402
    SEMENTES_OFICIAIS,
    Hiperparametros,
    Resultado,
    caminhos_de_saida,
    escolher_semente_publicada,
    estatisticas,
    gravar_sementes,
    resumir_sementes,
)

CONFIGURACAO = Hiperparametros(taxa_aprendizado=3e-5, epocas=3, lote=16)


def rodada(semente: int, f1: float, acuracia: float = 0.5) -> Resultado:
    """Uma rodada de treino sintética — só os números que os agregados usam."""
    return Resultado(
        hiperparametros=CONFIGURACAO,
        semente=semente,
        f1_macro=f1,
        acuracia=acuracia,
        f1_por_classe={"positivo": f1, "negativo": f1, "neutro": f1},
        perda_treino=[1.0],
        f1_por_epoca=[f1],
        melhor_epoca=1,
    )


CINCO = [
    rodada(42, 0.700),
    rodada(43, 0.620),
    rodada(44, 0.750),
    rodada(45, 0.680),
    rodada(46, 0.710),
]


# ------------------------------------------------------------------ as sementes


def test_sao_cinco_sementes_fixas_e_a_primeira_e_a_do_projeto():
    """Fixas, e não sorteadas: um número do TCC que muda a cada execução não é
    reproduzível. A primeira é a semente do projeto, que é também a da partição."""
    assert len(SEMENTES_OFICIAIS) == 5
    assert len(set(SEMENTES_OFICIAIS)) == 5
    assert SEMENTES_OFICIAIS[0] == SEMENTE


# ------------------------------------------------------------------ estatística


def test_desvio_e_amostral_e_nao_populacional():
    """Divisor n-1: as cinco sementes são uma amostra do sorteio de inicialização.

    Com n=5 o amostral sai 12% maior que o populacional, e reportar o menor dos dois
    faria a instabilidade do treino parecer menor do que é.
    """
    valores = [0.70, 0.62, 0.75, 0.68, 0.71]
    resumo = estatisticas(valores)

    media = sum(valores) / 5
    amostral = (sum((valor - media) ** 2 for valor in valores) / 4) ** 0.5
    populacional = (sum((valor - media) ** 2 for valor in valores) / 5) ** 0.5

    assert resumo["media"] == pytest.approx(media)
    assert resumo["desvio"] == pytest.approx(amostral)
    assert resumo["desvio"] != pytest.approx(populacional)


def test_estatisticas_traz_o_intervalo_inteiro():
    """Média sozinha esconde a rodada ruim; min e max são o que mostra o tamanho da
    oscilação para quem lê a tabela."""
    resumo = estatisticas([0.70, 0.62, 0.75, 0.68, 0.71])

    assert resumo["minimo"] == 0.62
    assert resumo["maximo"] == 0.75
    assert resumo["mediana"] == 0.70


def test_uma_semente_so_nao_tem_desvio():
    """O ensaio de fumaça roda com uma semente: desvio de uma amostra só não existe,
    e estourar aqui deixaria o teste de fumaça sem rodar."""
    assert estatisticas([0.7])["desvio"] == 0.0


# --------------------------------------------------------- quem vai para o disco


def test_publica_a_mediana_e_nao_a_melhor():
    """O ponto inteiro da escolha: publicar a melhor das cinco seria escolher pelo
    máximo de uma amostra, e o artefato sairia com um número sistematicamente acima da
    média que o relatório reporta duas linhas antes."""
    publicada = escolher_semente_publicada(CINCO)

    assert publicada.f1_macro == 0.700
    assert publicada.semente == 42
    assert publicada.f1_macro != max(resultado.f1_macro for resultado in CINCO)


def test_a_escolha_nao_depende_da_ordem_em_que_as_rodadas_chegaram():
    escolhas = {
        escolher_semente_publicada(lista).semente
        for lista in (CINCO, list(reversed(CINCO)), sorted(CINCO, key=lambda r: r.f1_macro))
    }
    assert escolhas == {42}


def test_empate_de_f1_e_desfeito_pela_semente():
    """Duas rodadas com o mesmo F1 não podem publicar modelos diferentes em execuções
    diferentes: sem critério de desempate, a ordem da lista decidiria qual sai."""
    empatadas = [rodada(43, 0.70), rodada(42, 0.70), rodada(44, 0.60)]

    assert escolher_semente_publicada(empatadas).semente == 42
    assert escolher_semente_publicada(list(reversed(empatadas))).semente == 42


def test_com_numero_par_de_sementes_sai_a_superior_das_centrais():
    """Só acontece no ensaio reduzido, mas precisa ser determinístico igual."""
    duas = [rodada(42, 0.60), rodada(43, 0.70)]
    assert escolher_semente_publicada(duas).semente == 43


# -------------------------------------------------------------------- o resumo


def test_o_resumo_diz_qual_semente_foi_publicada_e_por_que():
    resumo = resumir_sementes(CINCO, escolher_semente_publicada(CINCO))

    assert resumo["sementes"] == [42, 43, 44, 45, 46]
    assert resumo["semente_publicada"] == 42
    assert "mediana" in resumo["criterio_publicacao"]
    assert str(SEMENTE) in resumo["particao"]


def test_o_resumo_traz_media_desvio_e_as_cinco_linhas():
    """A média sem as rodadas seria um número sem prestação de contas: a tabela por
    semente é o que permite refazer a conta."""
    resumo = resumir_sementes(CINCO, escolher_semente_publicada(CINCO))

    assert resumo["f1_macro"]["media"] == pytest.approx(0.692)
    assert resumo["f1_macro"]["desvio"] > 0
    assert [linha["semente"] for linha in resumo["por_semente"]] == [42, 43, 44, 45, 46]
    assert [linha["f1_macro"] for linha in resumo["por_semente"]] == [
        0.700,
        0.620,
        0.750,
        0.680,
        0.710,
    ]


def test_o_relatorio_gravado_avisa_que_a_metrica_e_de_rotulo_fraco(tmp_path):
    """Daqui a seis meses ninguém lembra de qual JSON era qual — o aviso mora dentro
    do arquivo, como no `model_card.json` e no `busca_hiperparametros.json`."""
    caminho = tmp_path / "relatorio_sementes.json"
    resumo = resumir_sementes(CINCO, escolher_semente_publicada(CINCO))
    gravar_sementes(resumo, CONFIGURACAO, caminho)

    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    assert "rotulo fraco" in conteudo["aviso"].lower()
    assert "Capitulo 5" in conteudo["aviso"]
    assert conteudo["hiperparametros"]["taxa_aprendizado"] == 3e-5
    assert conteudo["semente_publicada"] == 42


# ------------------------------------------------- onde a rodada de fumaca grava


def test_o_ensaio_de_fumaca_nao_grava_onde_o_treino_oficial_grava():
    """Os três artefatos, e não só os dois JSON.

    A pasta do modelo não levava sufixo: `--limite 150` gravava os pesos de fumaça
    por cima dos do treino de verdade, que estão fora do git e custam uma sessão de
    T4. O cartão resultante dizia `treino: 128` no lugar de `1870` — legível, mas só
    para quem abrisse o arquivo e desconfiasse.
    """
    oficial = caminhos_de_saida(None, None)
    fumaca = caminhos_de_saida(150, None)

    colidindo = [a for a, b in zip(oficial, fumaca, strict=True) if a == b]
    assert not colidindo, f"o ensaio de fumaca grava por cima do oficial: {colidindo}"
    assert all("-reduzido" in caminho.name for caminho in fumaca)


def test_saida_explicita_vence_o_sufixo(tmp_path):
    """Quem escreve `--saida` na mão está dizendo onde quer, com ou sem `--limite`."""
    escolhida = tmp_path / "onde-eu-quero"

    assert caminhos_de_saida(150, escolhida)[2] == escolhida
    assert caminhos_de_saida(None, escolhida)[2] == escolhida


def test_o_notebook_e_o_script_usam_o_mesmo_sufixo():
    """As duas metades têm que combinar: o notebook monta `bertimbau-ensaio-reduzido`
    a partir de `RAIZ`, o script a partir de `ml/modelos/`. Sufixos diferentes dariam
    dois ensaios reduzidos que não são o mesmo, e só um deles estaria no .gitignore."""
    from ml.tests.test_notebook import caminhos_do_notebook

    do_notebook = caminhos_do_notebook(reduzido=True)
    _, _, do_script = caminhos_de_saida(150, None)

    assert do_notebook["MODELO"].name == do_script.name
