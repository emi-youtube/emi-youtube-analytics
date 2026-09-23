"""Testes da avaliação: métricas, bootstrap, leitura de previsões e figuras.

**O gabarito aqui é sintético** — o real ainda não voltou dos avaliadores. Nada toca
o banco: o caminho que lê `rotulo_humano` e `rotulo_fraco` é o único que exige
Postgres, e ele é exercitado pela via do CSV, que aceita qualquer conjunto de
previsões.

**Conferência independente.** As fórmulas são escritas à mão em `metricas.py`, e um
teste que só comparasse a implementação com ela mesma passaria com a fórmula errada.
Então cada métrica é conferida duas vezes:

1. contra um caso 3x3 **calculado à mão** na própria docstring, que é o que se mostra
   na banca;
2. contra o `scikit-learn`, em cem conjuntos sorteados — a mesma estratégia do Kappa,
   que é conferido contra os valores publicados de Fleiss (1971).

O `scikit-learn` é dependência só de desenvolvimento (`ml/requirements-dev.txt`):
onde ele não estiver instalado, esses testes são pulados e o resto continua valendo.
"""

import argparse
import csv
import random

import pytest

from ml.avaliacao.avaliar import (
    Avaliacao,
    avaliar_metodo,
    executar,
    gravar_relatorio,
    gravar_tabelas,
    ler_csv,
    validar_cobertura,
)
from ml.avaliacao.metricas import (
    avaliar_previsoes,
    intervalo_bootstrap,
    matriz_confusao,
    percentil,
)
from ml.config import CLASSES

# Caso 3x3 conferido à mão. Nove comentários, três por classe:
#
#   gabarito:  pos pos pos  neg neg neg  neu neu neu
#   previsto:  pos pos neg  neg neu neu  neu neu pos
#
#   positivo: VP=2 FP=1 FN=1 -> P=2/3  R=2/3  F1=0,6667
#   negativo: VP=1 FP=1 FN=2 -> P=1/2  R=1/3  F1=0,4000
#   neutro:   VP=2 FP=2 FN=1 -> P=1/2  R=2/3  F1=0,5714
#   acuracia = 5/9 = 0,5556      F1 macro = (0,6667+0,4+0,5714)/3 = 0,5460
GABARITO_MAO = ["positivo"] * 3 + ["negativo"] * 3 + ["neutro"] * 3
PREVISTO_MAO = [
    "positivo",
    "positivo",
    "negativo",
    "negativo",
    "neutro",
    "neutro",
    "neutro",
    "neutro",
    "positivo",
]


def sortear_rotulos(quantidade: int, semente: int) -> list[str]:
    sorteio = random.Random(semente)
    return [sorteio.choice(CLASSES) for _ in range(quantidade)]


# ------------------------------------------------------------------ conta feita à mão


def test_metricas_reproduzem_o_caso_calculado_a_mao():
    metricas = avaliar_previsoes(GABARITO_MAO, PREVISTO_MAO, CLASSES)

    assert metricas.acuracia == pytest.approx(5 / 9)
    assert metricas.por_classe["positivo"].f1 == pytest.approx(2 / 3)
    assert metricas.por_classe["negativo"].f1 == pytest.approx(0.4)
    assert metricas.por_classe["neutro"].f1 == pytest.approx(4 / 7)
    assert metricas.f1_macro == pytest.approx((2 / 3 + 0.4 + 4 / 7) / 3)


def test_matriz_de_confusao_tem_gabarito_na_linha_e_previsao_na_coluna():
    confusao = matriz_confusao(GABARITO_MAO, PREVISTO_MAO, CLASSES)

    assert confusao["positivo"]["positivo"] == 2
    assert confusao["positivo"]["negativo"] == 1
    assert confusao["neutro"]["positivo"] == 1
    assert sum(sum(linha.values()) for linha in confusao.values()) == 9


def test_f1_macro_nao_e_ponderado_pelo_suporte():
    """Com classe rara acertada e classe comum errada, macro e acurácia divergem.

    É o ponto da regra 8 do CLAUDE.md: a acurácia se deixa comprar pela classe
    majoritária, o F1 macro não.
    """
    gabarito = ["positivo"] * 90 + ["negativo"] * 10
    previsto = ["positivo"] * 100

    metricas = avaliar_previsoes(gabarito, previsto, CLASSES)
    assert metricas.acuracia == pytest.approx(0.9)
    assert metricas.f1_macro == pytest.approx(0.9473684 / 3, abs=1e-6)


def test_classe_sem_previsao_nenhuma_vale_zero_e_nao_estoura():
    metricas = avaliar_previsoes(["neutro", "neutro"], ["neutro", "neutro"], CLASSES)
    assert metricas.por_classe["positivo"].f1 == 0.0
    assert metricas.por_classe["positivo"].suporte == 0


def test_listas_desalinhadas_sao_recusadas():
    with pytest.raises(ValueError, match="alinhad"):
        avaliar_previsoes(["positivo"], ["positivo", "neutro"], CLASSES)


def test_listas_vazias_sao_recusadas():
    with pytest.raises(ValueError, match="vazias"):
        avaliar_previsoes([], [], CLASSES)


# ------------------------------------------------------------ conferencia com sklearn


def test_metricas_batem_com_o_scikit_learn():
    """Cem conjuntos sorteados, conferidos célula a célula contra a biblioteca."""
    metricas_sklearn = pytest.importorskip("sklearn.metrics")

    for semente in range(100):
        verdadeiros = sortear_rotulos(120, semente)
        previstos = sortear_rotulos(120, semente + 1000)
        nossas = avaliar_previsoes(verdadeiros, previstos, CLASSES)

        assert nossas.acuracia == pytest.approx(
            metricas_sklearn.accuracy_score(verdadeiros, previstos)
        )
        assert nossas.f1_macro == pytest.approx(
            metricas_sklearn.f1_score(
                verdadeiros, previstos, average="macro", labels=list(CLASSES), zero_division=0
            )
        )
        assert nossas.precisao_macro == pytest.approx(
            metricas_sklearn.precision_score(
                verdadeiros, previstos, average="macro", labels=list(CLASSES), zero_division=0
            )
        )
        assert nossas.revocacao_macro == pytest.approx(
            metricas_sklearn.recall_score(
                verdadeiros, previstos, average="macro", labels=list(CLASSES), zero_division=0
            )
        )

        f1_por_classe = metricas_sklearn.f1_score(
            verdadeiros, previstos, average=None, labels=list(CLASSES), zero_division=0
        )
        for classe, esperado in zip(CLASSES, f1_por_classe, strict=True):
            assert nossas.por_classe[classe].f1 == pytest.approx(esperado)


def test_matriz_de_confusao_bate_com_o_scikit_learn():
    metricas_sklearn = pytest.importorskip("sklearn.metrics")

    verdadeiros = sortear_rotulos(200, 7)
    previstos = sortear_rotulos(200, 8)
    deles = metricas_sklearn.confusion_matrix(verdadeiros, previstos, labels=list(CLASSES))
    nossa = matriz_confusao(verdadeiros, previstos, CLASSES)

    for indice_linha, linha in enumerate(CLASSES):
        for indice_coluna, coluna in enumerate(CLASSES):
            assert nossa[linha][coluna] == deles[indice_linha][indice_coluna]


def test_convencao_de_divisao_por_zero_e_a_mesma_do_sklearn():
    """Classe que ninguém previu vale 0,0 — `zero_division=0`, não `nan`."""
    metricas_sklearn = pytest.importorskip("sklearn.metrics")

    verdadeiros = ["positivo"] * 5 + ["neutro"] * 5
    previstos = ["neutro"] * 10

    nossas = avaliar_previsoes(verdadeiros, previstos, CLASSES)
    assert nossas.f1_macro == pytest.approx(
        metricas_sklearn.f1_score(
            verdadeiros, previstos, average="macro", labels=list(CLASSES), zero_division=0
        )
    )


def test_a_media_macro_e_sempre_sobre_as_TRES_classes_do_projeto():
    """Divergência deliberada do `f1_score` PADRÃO do scikit-learn — e ela importa.

    Sem `labels=`, o scikit-learn faz a média macro só sobre as classes que aparecem
    nos dados: um conjunto onde ninguém previu (nem havia) `negativo` seria dividido
    por 2, não por 3. Aqui o denominador é sempre 3, porque as três classes são
    fechadas no banco (CHECK) e não dependem da amostra.

    A diferença não é acadêmica: dois métodos medidos com denominadores diferentes
    deixariam de ser comparáveis, e é comparação que o Capítulo 5 faz. Quem refizer a
    conta num notebook precisa passar `labels=['positivo','negativo','neutro']` para
    chegar ao mesmo número.
    """
    metricas_sklearn = pytest.importorskip("sklearn.metrics")

    verdadeiros = ["positivo"] * 5 + ["neutro"] * 5
    previstos = ["neutro"] * 10

    nosso = avaliar_previsoes(verdadeiros, previstos, CLASSES).f1_macro
    padrao_do_sklearn = metricas_sklearn.f1_score(
        verdadeiros, previstos, average="macro", zero_division=0
    )

    assert nosso == pytest.approx((0 + 0 + 2 / 3) / 3)
    assert padrao_do_sklearn == pytest.approx((0 + 2 / 3) / 2)
    assert nosso != pytest.approx(padrao_do_sklearn)


def test_percentil_bate_com_o_numpy():
    numpy = pytest.importorskip("numpy")

    valores = [0.1, 0.35, 0.42, 0.5, 0.77, 0.81, 0.9]
    for fracao in (0.0, 0.025, 0.25, 0.5, 0.975, 1.0):
        assert percentil(valores, fracao) == pytest.approx(
            float(numpy.percentile(valores, 100 * fracao))
        )


# ---------------------------------------------------------------------- bootstrap


def test_intervalo_contem_o_valor_pontual():
    verdadeiros = sortear_rotulos(300, 1)
    previstos = [
        rotulo if indice % 4 else "neutro" for indice, rotulo in enumerate(verdadeiros)
    ]
    metricas = avaliar_previsoes(verdadeiros, previstos, CLASSES)
    intervalos = intervalo_bootstrap(verdadeiros, previstos, CLASSES, reamostragens=400)

    inferior, superior = intervalos["macro"]
    assert inferior <= metricas.f1_macro <= superior
    for classe in CLASSES:
        inferior, superior = intervalos[classe]
        assert inferior <= metricas.por_classe[classe].f1 <= superior


def test_intervalo_e_deterministico_com_a_mesma_semente():
    """O número publicado no TCC tem que sair igual em qualquer máquina."""
    verdadeiros = sortear_rotulos(150, 3)
    previstos = sortear_rotulos(150, 4)

    primeiro = intervalo_bootstrap(verdadeiros, previstos, CLASSES, reamostragens=200)
    segundo = intervalo_bootstrap(verdadeiros, previstos, CLASSES, reamostragens=200)
    assert primeiro == segundo


def test_semente_diferente_muda_o_intervalo():
    verdadeiros = sortear_rotulos(150, 3)
    previstos = sortear_rotulos(150, 4)

    padrao = intervalo_bootstrap(verdadeiros, previstos, CLASSES, reamostragens=200)
    outra = intervalo_bootstrap(
        verdadeiros, previstos, CLASSES, reamostragens=200, semente=99
    )
    assert padrao != outra


def test_amostra_maior_estreita_o_intervalo():
    """A largura é o que o Capítulo 5 usa para dizer se dois métodos diferem."""
    sorteio = random.Random(11)

    def montar(quantidade: int) -> tuple[list[str], list[str]]:
        verdadeiros = [sorteio.choice(CLASSES) for _ in range(quantidade)]
        previstos = [
            rotulo if sorteio.random() < 0.75 else sorteio.choice(CLASSES)
            for rotulo in verdadeiros
        ]
        return verdadeiros, previstos

    pequena = intervalo_bootstrap(*montar(60), CLASSES, reamostragens=400)["macro"]
    grande = intervalo_bootstrap(*montar(900), CLASSES, reamostragens=400)["macro"]

    assert (grande[1] - grande[0]) < (pequena[1] - pequena[0])


def test_bootstrap_exige_ao_menos_uma_reamostragem():
    with pytest.raises(ValueError, match="reamostragem"):
        intervalo_bootstrap(["neutro"], ["neutro"], CLASSES, reamostragens=0)


# ------------------------------------------------------------- leitura das previsoes


def escrever_csv(caminho, linhas, coluna="previsto"):
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["id_comentario", coluna])
        escritor.writerows(linhas)
    return caminho


def test_le_csv_de_previsoes(tmp_path):
    caminho = escrever_csv(tmp_path / "p.csv", [(1, "positivo"), (2, "neutro")])
    rotulos, problemas = ler_csv(caminho, "lexico")

    assert rotulos == {1: "positivo", 2: "neutro"}
    assert problemas == []


def test_aceita_outros_nomes_para_a_coluna_de_rotulo(tmp_path):
    """"qualquer conjunto de previsões" inclui o CSV que o Colab vai exportar."""
    caminho = escrever_csv(tmp_path / "p.csv", [(1, "positivo")], coluna="sentimento")
    rotulos, problemas = ler_csv(caminho, "bertimbau")

    assert rotulos == {1: "positivo"}
    assert problemas == []


def test_rotulo_fora_das_classes_e_reportado_com_endereco(tmp_path):
    caminho = escrever_csv(tmp_path / "p.csv", [(1, "Positivo"), (2, "neutro")])
    rotulos, problemas = ler_csv(caminho, "lexico")

    assert rotulos == {2: "neutro"}
    assert len(problemas) == 1
    assert "linha 2" in str(problemas[0]) and "id 1" in str(problemas[0])


def test_id_repetido_e_reportado(tmp_path):
    caminho = escrever_csv(tmp_path / "p.csv", [(1, "positivo"), (1, "neutro")])
    _, problemas = ler_csv(caminho, "lexico")

    assert "repetido" in str(problemas[0])


def test_csv_sem_coluna_de_rotulo_falha_cedo(tmp_path):
    caminho = tmp_path / "p.csv"
    caminho.write_text("id_comentario,escore\n1,3\n", encoding="utf-8")
    rotulos, problemas = ler_csv(caminho, "lexico")

    assert rotulos == {}
    assert "sem coluna de rotulo" in str(problemas[0])


def test_arquivo_ausente_vira_problema_e_nao_excecao(tmp_path):
    _, problemas = ler_csv(tmp_path / "nao_existe.csv", "lexico")
    assert "nao encontrado" in str(problemas[0])


def test_comentario_do_gabarito_sem_previsao_e_erro():
    problemas = validar_cobertura({1: "positivo", 2: "neutro"}, {1: "positivo"}, "lexico")
    assert len(problemas) == 1
    assert "id 2" in str(problemas[0])


def test_previsao_sobrando_nao_e_problema():
    """O conjunto avaliado é o do gabarito; método que classificou mais pode entrar."""
    assert validar_cobertura({1: "positivo"}, {1: "positivo", 9: "neutro"}, "lexico") == []


# ------------------------------------------------------------------- fim a fim


def montar_argumentos(tmp_path, **extras) -> argparse.Namespace:
    padrao = {
        "id_execucao": None,
        "gabarito": None,
        "previsoes": [],
        "gemini": False,
        "saida": tmp_path / "saida",
        "reamostragens": 200,
        "sem_graficos": True,
    }
    padrao.update(extras)
    return argparse.Namespace(**padrao)


@pytest.fixture
def ensaio(tmp_path):
    """Gabarito sintético e dois métodos: um bom e um que só chuta `neutro`."""
    sorteio = random.Random(5)
    ids = list(range(1, 121))
    gabarito = {id_comentario: sorteio.choice(CLASSES) for id_comentario in ids}
    bom = {
        id_comentario: (
            rotulo if sorteio.random() < 0.8 else sorteio.choice(CLASSES)
        )
        for id_comentario, rotulo in gabarito.items()
    }
    preguicoso = dict.fromkeys(ids, "neutro")

    escrever_csv(tmp_path / "gabarito.csv", sorted(gabarito.items()), coluna="rotulo_humano")
    escrever_csv(tmp_path / "bom.csv", sorted(bom.items()))
    escrever_csv(tmp_path / "preguicoso.csv", sorted(preguicoso.items()))
    return tmp_path


def test_executa_fim_a_fim_com_gabarito_sintetico(ensaio):
    argumentos = montar_argumentos(
        ensaio,
        gabarito=ensaio / "gabarito.csv",
        previsoes=[f"bom={ensaio / 'bom.csv'}", f"preguicoso={ensaio / 'preguicoso.csv'}"],
    )
    avaliacoes, excluidos, origem = executar(argumentos)

    assert [avaliacao.metodo for avaliacao in avaliacoes] == ["bom", "preguicoso"]
    assert excluidos == 0
    assert "csv" in origem
    assert avaliacoes[0].metricas.f1_macro > avaliacoes[1].metricas.f1_macro
    assert avaliacoes[0].metricas.total == 120


def test_metodo_que_chuta_uma_classe_so_afunda_no_macro(ensaio):
    argumentos = montar_argumentos(
        ensaio,
        gabarito=ensaio / "gabarito.csv",
        previsoes=[f"preguicoso={ensaio / 'preguicoso.csv'}"],
    )
    (avaliacao,), _, _ = executar(argumentos)

    assert avaliacao.metricas.por_classe["positivo"].f1 == 0.0
    assert avaliacao.metricas.f1_macro < 0.2


def test_validacao_falha_alto_e_nao_calcula_nada(ensaio):
    faltando = ensaio / "faltando.csv"
    escrever_csv(faltando, [(1, "positivo")])
    argumentos = montar_argumentos(
        ensaio, gabarito=ensaio / "gabarito.csv", previsoes=[f"parcial={faltando}"]
    )

    with pytest.raises(SystemExit):
        executar(argumentos)


def test_sem_metodo_nao_ha_o_que_avaliar(ensaio):
    argumentos = montar_argumentos(ensaio, gabarito=ensaio / "gabarito.csv")
    with pytest.raises(SystemExit, match="nenhum metodo"):
        executar(argumentos)


def test_previsoes_em_formato_errado_sao_recusadas(ensaio):
    argumentos = montar_argumentos(
        ensaio, gabarito=ensaio / "gabarito.csv", previsoes=["sem_igual.csv"]
    )
    with pytest.raises(SystemExit, match="nome=caminho"):
        executar(argumentos)


def test_gabarito_do_banco_exige_id_execucao(ensaio):
    """Sem `--gabarito` a fonte é o banco, e aí a execução é obrigatória."""
    argumentos = montar_argumentos(ensaio, previsoes=[f"bom={ensaio / 'bom.csv'}"])
    with pytest.raises(SystemExit, match="id-execucao"):
        executar(argumentos)


# ----------------------------------------------------------------------- saidas


def test_grava_tabelas_e_relatorio(ensaio, tmp_path):
    argumentos = montar_argumentos(
        ensaio, gabarito=ensaio / "gabarito.csv", previsoes=[f"bom={ensaio / 'bom.csv'}"]
    )
    avaliacoes, excluidos, origem = executar(argumentos)

    saida = tmp_path / "saida"
    gravar_tabelas(avaliacoes, saida)
    gravar_relatorio(avaliacoes, excluidos, origem, 200, saida / "resultado_avaliacao.json")

    markdown = (saida / "tabela_metricas.md").read_text(encoding="utf-8")
    assert "F1 macro" in markdown
    assert "Matriz" in markdown or "matriz" in markdown

    linhas = list(csv.DictReader((saida / "tabela_metricas.csv").open(encoding="utf-8")))
    assert len(linhas) == len(CLASSES)
    assert {linha["classe"] for linha in linhas} == set(CLASSES)

    relatorio = (saida / "resultado_avaliacao.json").read_text(encoding="utf-8")
    assert "f1_macro" in relatorio and "ic95_f1" in relatorio


def test_gera_as_figuras_do_capitulo(ensaio, tmp_path):
    pytest.importorskip("matplotlib")
    from ml.avaliacao.graficos import gerar_figuras

    argumentos = montar_argumentos(
        ensaio,
        gabarito=ensaio / "gabarito.csv",
        previsoes=[f"lexico={ensaio / 'bom.csv'}", f"preguicoso={ensaio / 'preguicoso.csv'}"],
    )
    avaliacoes, _, _ = executar(argumentos)
    caminhos = gerar_figuras(avaliacoes, tmp_path / "figuras")

    assert [caminho.name for caminho in caminhos] == [
        "f1_macro.png",
        "f1_por_classe.png",
        "confusao_lexico.png",
        "confusao_preguicoso.png",
    ]
    assert all(caminho.stat().st_size > 0 for caminho in caminhos)


def test_cor_segue_o_metodo_e_nao_a_posicao():
    """Léxico não muda de tom porque o BERTimbau entrou na comparação."""
    pytest.importorskip("matplotlib")
    from ml.avaliacao.graficos import cor_do_metodo

    assert cor_do_metodo("lexico", 0) == cor_do_metodo("lexico", 2)
    assert cor_do_metodo("lexico", 0) != cor_do_metodo("gemini (rotulo_fraco)", 1)


def test_avaliar_metodo_alinha_por_id_e_nao_por_posicao():
    """As previsões podem vir em qualquer ordem — o alinhamento é pelo id."""
    gabarito = {10: "positivo", 20: "negativo", 30: "neutro"}
    embaralhado = {30: "neutro", 10: "positivo", 20: "negativo"}

    avaliacao = avaliar_metodo("teste", "memoria", gabarito, embaralhado, 50)
    assert isinstance(avaliacao, Avaliacao)
    assert avaliacao.metricas.acuracia == 1.0
