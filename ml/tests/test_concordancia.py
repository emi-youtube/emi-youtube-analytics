"""Testes da concordância entre avaliadores.

Nada toca o banco e nada depende das planilhas reais — elas ainda não voltaram. As
planilhas sintéticas são montadas aqui com o mesmo formato que
`gerar_planilhas_avaliadores.py` produz, o que também serve de teste de contrato
entre os dois módulos: se o gerador mudar de coluna, estes testes quebram.

Os dois Kappas são conferidos contra valores publicados (Fleiss 1971; o exemplo 2x2
clássico de Cohen), e não contra o que esta implementação devolve hoje. Teste que só
compara o código com ele mesmo passaria com a fórmula errada.
"""

import math

import pytest
from openpyxl import Workbook

from ml.concordancia.calcular_concordancia import (
    AVALIADORES,
    apurar,
    executar,
    ler_planilha,
    validar_conjuntos,
)
from ml.concordancia.kappa import (
    META_KAPPA,
    ConcordanciaDegenerada,
    classificar_landis_koch,
    kappa_cohen,
    kappa_fleiss,
    kappa_fleiss_por_classe,
    matriz_confusao,
    matriz_de_contagem,
    matriz_divergencia,
    voto_majoritario,
)
from ml.config import CLASSES

# --------------------------------------------------------------- Kappa de Fleiss

# Exemplo canonico de Fleiss (1971): 10 sujeitos, 14 avaliadores, 5 categorias.
# Resultado publicado: P_bar = 0,378; P_e = 0,213; kappa = 0,209.
FLEISS_1971 = [
    (0, 0, 0, 0, 14),
    (0, 2, 6, 4, 2),
    (0, 0, 3, 5, 6),
    (0, 3, 9, 2, 0),
    (2, 2, 8, 1, 1),
    (7, 7, 0, 0, 0),
    (3, 2, 6, 3, 0),
    (2, 5, 3, 2, 2),
    (6, 5, 2, 1, 0),
    (0, 2, 2, 3, 7),
]


def test_fleiss_reproduz_o_valor_publicado_de_1971():
    assert kappa_fleiss(FLEISS_1971) == pytest.approx(0.209, abs=0.001)


def test_fleiss_e_1_quando_todos_concordam_em_tudo():
    contagens = [(3, 0, 0), (0, 3, 0), (0, 0, 3), (3, 0, 0)]
    assert kappa_fleiss(contagens) == pytest.approx(1.0)


def test_fleiss_estoura_quando_so_existe_uma_classe():
    """Todo mundo marcou 'positivo' em tudo: concordancia total, Kappa indefinido."""
    with pytest.raises(ConcordanciaDegenerada):
        kappa_fleiss([(3, 0, 0), (3, 0, 0), (3, 0, 0)])


def test_fleiss_fica_negativo_quando_a_discordancia_supera_o_acaso():
    """Todo item 2-1 dividido: concordam menos do que se sorteassem."""
    contagens = [(2, 1, 0), (1, 2, 0), (2, 1, 0), (1, 2, 0)]
    assert kappa_fleiss(contagens) < 0


def test_fleiss_recusa_item_com_numero_diferente_de_avaliadores():
    """Planilha entregue pela metade nao pode virar um Kappa silenciosamente menor."""
    with pytest.raises(ValueError, match="mesmo numero de avaliadores"):
        kappa_fleiss([(3, 0, 0), (2, 0, 0)])


def test_fleiss_recusa_matriz_vazia():
    with pytest.raises(ValueError):
        kappa_fleiss([])


# ---------------------------------------------------------------- Kappa de Cohen


def test_cohen_reproduz_o_exemplo_2x2_classico():
    """20 sim/sim, 5 sim/nao, 10 nao/sim, 15 nao/nao -> p_o=0,70; p_e=0,50; kappa=0,40."""
    a = ["sim"] * 20 + ["sim"] * 5 + ["nao"] * 10 + ["nao"] * 15
    b = ["sim"] * 20 + ["nao"] * 5 + ["sim"] * 10 + ["nao"] * 15
    assert kappa_cohen(a, b) == pytest.approx(0.40)


def test_cohen_e_1_em_concordancia_perfeita():
    rotulos = ["positivo", "negativo", "neutro", "positivo"]
    assert kappa_cohen(rotulos, rotulos) == pytest.approx(1.0)


def test_cohen_estoura_em_classe_unica():
    with pytest.raises(ConcordanciaDegenerada):
        kappa_cohen(["neutro"] * 5, ["neutro"] * 5)


def test_cohen_recusa_listas_desalinhadas():
    with pytest.raises(ValueError, match="alinhados por id_comentario"):
        kappa_cohen(["positivo", "neutro"], ["positivo"])


def test_cohen_e_simetrico():
    a = ["positivo", "neutro", "negativo", "positivo", "neutro"]
    b = ["positivo", "negativo", "negativo", "neutro", "neutro"]
    assert kappa_cohen(a, b) == pytest.approx(kappa_cohen(b, a))


# ------------------------------------------------------------ Landis e Koch


@pytest.mark.parametrize(
    ("kappa", "faixa"),
    [
        (-0.1, "pobre"),
        (0.10, "leve"),
        (0.30, "razoavel"),
        (0.50, "moderada"),
        (0.70, "substancial"),
        (0.90, "quase perfeita"),
        (1.00, "quase perfeita"),
    ],
)
def test_faixas_de_landis_koch(kappa, faixa):
    assert classificar_landis_koch(kappa) == faixa


def test_a_meta_do_projeto_cai_na_faixa_substancial():
    """O manual chama 0,60 de 'substancial'; e o piso da faixa em Landis e Koch."""
    assert classificar_landis_koch(META_KAPPA) == "substancial"


# ------------------------------------------------------------- Voto majoritário


def test_voto_unanime():
    assert voto_majoritario(["positivo"] * 3) == "positivo"


def test_voto_de_maioria_simples():
    assert voto_majoritario(["positivo", "positivo", "neutro"]) == "positivo"


def test_empate_de_tres_vias_nao_tem_vencedor():
    """1-1-1 vai para a reuniao — desempatar por ordem embutiria o voto do primeiro."""
    assert voto_majoritario(["positivo", "negativo", "neutro"]) is None


def test_voto_independe_da_ordem():
    assert voto_majoritario(["neutro", "positivo", "positivo"]) == "positivo"
    assert voto_majoritario(["positivo", "neutro", "positivo"]) == "positivo"


# ------------------------------------------------------------------- Matrizes


def test_matriz_de_contagem_conta_votos_por_classe():
    votos = [["positivo", "positivo", "neutro"], ["negativo"] * 3]
    contagens = matriz_de_contagem(votos, CLASSES)
    assert contagens[0][CLASSES.index("positivo")] == 2
    assert contagens[0][CLASSES.index("neutro")] == 1
    assert contagens[1][CLASSES.index("negativo")] == 3


def test_matriz_de_confusao_poe_a_concordancia_na_diagonal():
    a = ["positivo", "positivo", "neutro"]
    b = ["positivo", "neutro", "neutro"]
    matriz = matriz_confusao(a, b, CLASSES)
    assert matriz["positivo"]["positivo"] == 1
    assert matriz["positivo"]["neutro"] == 1
    assert matriz["neutro"]["neutro"] == 1


def test_matriz_de_divergencia_e_simetrica():
    rotulos = [
        ["positivo", "neutro", "negativo"],
        ["neutro", "neutro", "positivo"],
        ["positivo", "negativo", "negativo"],
    ]
    matriz = matriz_divergencia(rotulos, CLASSES)
    for linha in CLASSES:
        for coluna in CLASSES:
            assert matriz[linha][coluna] == matriz[coluna][linha]


def test_fleiss_por_classe_isola_a_classe_problematica():
    """positivo e negativo unanimes; neutro sempre dividido -> neutro tem o pior Kappa."""
    votos = [
        ["positivo"] * 3,
        ["positivo"] * 3,
        ["negativo"] * 3,
        ["negativo"] * 3,
        ["neutro", "neutro", "positivo"],
        ["neutro", "positivo", "neutro"],
    ]
    por_classe = kappa_fleiss_por_classe(matriz_de_contagem(votos, CLASSES), CLASSES)
    assert por_classe["neutro"] < por_classe["positivo"]
    assert por_classe["neutro"] < por_classe["negativo"]


def test_fleiss_por_classe_pula_classe_que_ninguem_usou():
    votos = [["positivo"] * 3, ["negativo"] * 3]
    por_classe = kappa_fleiss_por_classe(matriz_de_contagem(votos, CLASSES), CLASSES)
    assert "neutro" not in por_classe


# ------------------------------------------------- Planilhas sintéticas (fixture)


def montar_resposta(caminho, linhas, com_aba=True):
    """Escreve uma planilha no formato de `gerar_planilhas_avaliadores.py`.

    `linhas` e uma lista de (id_comentario, texto, rotulo, duvida, observacao).
    """
    livro = Workbook()
    aba = livro.active
    aba.title = "rotulagem" if com_aba else "outra_coisa"
    aba.append(["id_comentario", "texto", "rotulo", "duvida", "observacao"])
    for linha in linhas:
        aba.append(list(linha))
    livro.save(caminho)


def escrever_trio(diretorio, rotulos_por_avaliador, duvidas=None, textos=None):
    """Monta as tres planilhas a partir de {avaliador: [rotulos]}, mesma ordem de ids."""
    total = len(next(iter(rotulos_por_avaliador.values())))
    ids = list(range(1, total + 1))
    for avaliador, rotulos in rotulos_por_avaliador.items():
        marcadas = (duvidas or {}).get(avaliador, set())
        linhas = [
            (
                id_comentario,
                (textos or {}).get(id_comentario, f"comentario {id_comentario}"),
                rotulo,
                "sim" if id_comentario in marcadas else "nao",
                "",
            )
            for id_comentario, rotulo in zip(ids, rotulos, strict=True)
        ]
        montar_resposta(diretorio / f"{avaliador}.xlsx", linhas)
    return ids


def test_fluxo_completo_com_planilhas_sinteticas(tmp_path):
    rotulos = {
        "avaliador_1": ["positivo", "positivo", "neutro", "negativo", "neutro", "positivo"],
        "avaliador_2": ["positivo", "neutro", "neutro", "negativo", "negativo", "positivo"],
        "avaliador_3": ["positivo", "negativo", "neutro", "negativo", "positivo", "neutro"],
    }
    escrever_trio(tmp_path, rotulos)

    resultado, _ = executar(tmp_path, normalizar=False)

    assert resultado.total == 6
    assert resultado.fleiss is not None
    assert len(resultado.cohen_por_par) == 3
    assert set(resultado.cohen_por_par) == {
        "avaliador_1 x avaliador_2",
        "avaliador_1 x avaliador_3",
        "avaliador_2 x avaliador_3",
    }
    # id 1 e 4: unanimes. id 2: 1-1-1. id 3: unanime. id 5: 1-1-1. id 6: 2-1 positivo.
    assert resultado.unanimes == 3
    assert resultado.maioria_simples == 1
    assert sorted(resultado.empates) == [2, 5]
    assert resultado.gabarito[6] == "positivo"
    assert 2 not in resultado.gabarito


def test_concordancia_perfeita_da_kappa_1_e_gabarito_completo(tmp_path):
    rotulos = {
        avaliador: ["positivo", "neutro", "negativo", "positivo", "neutro"]
        for avaliador in AVALIADORES
    }
    escrever_trio(tmp_path, rotulos)

    resultado, _ = executar(tmp_path, normalizar=False)

    assert resultado.fleiss == pytest.approx(1.0)
    assert all(valor == pytest.approx(1.0) for valor in resultado.cohen_por_par.values())
    assert resultado.atingiu_meta
    assert len(resultado.gabarito) == 5
    assert resultado.empates == []
    assert resultado.unanimes == 5


def test_a_ordem_das_linhas_nao_muda_o_kappa(tmp_path):
    """As tres planilhas reais saem embaralhadas de propósito (semente por avaliador).

    Se o calculo alinhasse por posicao de linha em vez de por id_comentario, este
    teste daria um Kappa diferente — e seria exatamente o bug que ninguem veria.
    """
    rotulos = {
        "avaliador_1": ["positivo", "neutro", "negativo", "positivo", "neutro", "negativo"],
        "avaliador_2": ["positivo", "neutro", "positivo", "positivo", "negativo", "negativo"],
        "avaliador_3": ["neutro", "neutro", "negativo", "positivo", "neutro", "positivo"],
    }

    direto = tmp_path / "direto"
    direto.mkdir()
    escrever_trio(direto, rotulos)
    esperado, _ = executar(direto, normalizar=False)

    embaralhado = tmp_path / "embaralhado"
    embaralhado.mkdir()
    for indice, (avaliador, lista) in enumerate(rotulos.items()):
        pares = list(enumerate(lista, start=1))
        # Rotaciona de um jeito diferente por avaliador, como as sementes derivadas fazem.
        pares = pares[indice + 1 :] + pares[: indice + 1]
        montar_resposta(
            embaralhado / f"{avaliador}.xlsx",
            [
                (id_comentario, f"comentario {id_comentario}", rotulo, "nao", "")
                for id_comentario, rotulo in pares
            ],
        )
    obtido, _ = executar(embaralhado, normalizar=False)

    assert obtido.fleiss == pytest.approx(esperado.fleiss)
    assert obtido.cohen_por_par == pytest.approx(esperado.cohen_por_par)
    assert obtido.gabarito == esperado.gabarito


def test_duvida_de_dois_avaliadores_entra_na_pauta_mesmo_com_rotulo_unanime(tmp_path):
    rotulos = {
        avaliador: ["positivo", "neutro", "negativo", "positivo"]
        for avaliador in AVALIADORES
    }
    duvidas = {"avaliador_1": {2}, "avaliador_2": {2}, "avaliador_3": set()}
    escrever_trio(tmp_path, rotulos, duvidas=duvidas)

    resultado, _ = executar(tmp_path, normalizar=False)

    assert resultado.empates == []
    assert resultado.duvidas_coletivas == [2]
    assert resultado.desempate == [2]
    # Mesmo na pauta, o rotulo unanime continua valendo como gabarito.
    assert resultado.gabarito[2] == "neutro"


def test_duvida_de_um_avaliador_so_nao_entra_na_pauta(tmp_path):
    rotulos = {
        avaliador: ["positivo", "neutro", "negativo", "positivo"]
        for avaliador in AVALIADORES
    }
    duvidas = {"avaliador_1": {3}, "avaliador_2": set(), "avaliador_3": set()}
    escrever_trio(tmp_path, rotulos, duvidas=duvidas)

    resultado, _ = executar(tmp_path, normalizar=False)
    assert resultado.duvidas_coletivas == []


# ------------------------------------------------------------------ Validações


def test_rotulo_vazio_falha_alto(tmp_path):
    montar_resposta(tmp_path / "avaliador_1.xlsx", [(1, "a", "positivo", "nao", "")])
    montar_resposta(tmp_path / "avaliador_2.xlsx", [(1, "a", "", "nao", "")])
    montar_resposta(tmp_path / "avaliador_3.xlsx", [(1, "a", "neutro", "nao", "")])

    with pytest.raises(SystemExit):
        executar(tmp_path, normalizar=False)


def test_rotulo_fora_das_classes_falha_alto(tmp_path):
    montar_resposta(tmp_path / "avaliador_1.xlsx", [(1, "a", "misto", "nao", "")])
    _, problemas = ler_planilha(tmp_path / "avaliador_1.xlsx", "avaliador_1", normalizar=False)
    assert any("fora das classes" in problema.descricao for problema in problemas)


def test_variacao_tipografica_e_recusada_por_padrao(tmp_path):
    """'Positivo ' com maiuscula e espaco e o caso que o card manda nao deixar passar."""
    montar_resposta(tmp_path / "avaliador_1.xlsx", [(1, "a", "Positivo ", "nao", "")])
    respostas, problemas = ler_planilha(
        tmp_path / "avaliador_1.xlsx", "avaliador_1", normalizar=False
    )
    assert respostas == []
    assert any("so por espaco/maiuscula" in problema.descricao for problema in problemas)


def test_variacao_tipografica_com_normalizar_passa_mas_fica_registrada(tmp_path):
    montar_resposta(tmp_path / "avaliador_1.xlsx", [(1, "a", "Positivo ", "nao", "")])
    respostas, problemas = ler_planilha(
        tmp_path / "avaliador_1.xlsx", "avaliador_1", normalizar=True
    )
    assert [resposta.rotulo for resposta in respostas] == ["positivo"]
    assert any(problema.descricao.startswith("NORMALIZADO") for problema in problemas)


def test_planilhas_com_ids_diferentes_falham_alto(tmp_path):
    montar_resposta(tmp_path / "avaliador_1.xlsx", [(1, "a", "positivo", "nao", "")])
    montar_resposta(tmp_path / "avaliador_2.xlsx", [(2, "b", "positivo", "nao", "")])
    montar_resposta(tmp_path / "avaliador_3.xlsx", [(1, "a", "positivo", "nao", "")])

    with pytest.raises(SystemExit):
        executar(tmp_path, normalizar=False)


def test_id_faltando_em_uma_planilha_e_apontado_com_o_id(tmp_path):
    por_avaliador = {
        "avaliador_1": [],
        "avaliador_2": [],
    }
    montar_resposta(
        tmp_path / "a.xlsx", [(1, "a", "positivo", "nao", ""), (2, "b", "neutro", "nao", "")]
    )
    montar_resposta(tmp_path / "b.xlsx", [(1, "a", "positivo", "nao", "")])
    por_avaliador["avaliador_1"], _ = ler_planilha(tmp_path / "a.xlsx", "avaliador_1", False)
    por_avaliador["avaliador_2"], _ = ler_planilha(tmp_path / "b.xlsx", "avaliador_2", False)

    ids, problemas = validar_conjuntos(por_avaliador)
    assert ids == [1]
    assert any(problema.id_comentario == 2 for problema in problemas)


def test_id_repetido_na_mesma_planilha_e_apontado(tmp_path):
    montar_resposta(
        tmp_path / "avaliador_1.xlsx",
        [(1, "a", "positivo", "nao", ""), (1, "a", "neutro", "nao", "")],
    )
    _, problemas = ler_planilha(tmp_path / "avaliador_1.xlsx", "avaliador_1", normalizar=False)
    assert any("repetido" in problema.descricao for problema in problemas)


def test_arquivo_ausente_vira_problema_e_nao_excecao(tmp_path):
    _, problemas = ler_planilha(tmp_path / "nao_existe.xlsx", "avaliador_1", normalizar=False)
    assert any("nao encontrado" in problema.descricao for problema in problemas)


def test_planilha_sem_a_aba_rotulagem_e_apontada(tmp_path):
    montar_resposta(
        tmp_path / "avaliador_1.xlsx", [(1, "a", "positivo", "nao", "")], com_aba=False
    )
    _, problemas = ler_planilha(tmp_path / "avaliador_1.xlsx", "avaliador_1", normalizar=False)
    assert any("aba" in problema.descricao for problema in problemas)


def test_linhas_em_branco_no_fim_sao_ignoradas(tmp_path):
    """O Excel costuma guardar linhas vazias depois da ultima preenchida."""
    caminho = tmp_path / "avaliador_1.xlsx"
    livro = Workbook()
    aba = livro.active
    aba.title = "rotulagem"
    aba.append(["id_comentario", "texto", "rotulo", "duvida", "observacao"])
    aba.append([1, "a", "positivo", "nao", ""])
    aba.append([None, None, None, None, None])
    aba.append([None, None, None, None, None])
    livro.save(caminho)

    respostas, problemas = ler_planilha(caminho, "avaliador_1", normalizar=False)
    assert len(respostas) == 1
    assert problemas == []


def test_o_relatorio_nao_carrega_texto_de_terceiros(tmp_path):
    """O JSON e commitavel; as planilhas nao. A fronteira e esta."""
    from ml.concordancia.calcular_concordancia import gravar_relatorio

    segredo = "texto original de um comentario de terceiro"
    rotulos = {
        avaliador: ["positivo", "neutro", "negativo"]
        for avaliador in AVALIADORES
    }
    escrever_trio(
        tmp_path,
        rotulos,
        textos={1: segredo, 2: segredo, 3: segredo},
    )
    resultado, _ = executar(tmp_path, normalizar=False)

    destino = tmp_path / "resultado.json"
    gravar_relatorio(resultado, destino)
    assert segredo not in destino.read_text(encoding="utf-8")


def test_pauta_do_desempate_sai_com_os_tres_votos(tmp_path):
    from openpyxl import load_workbook

    from ml.concordancia.calcular_concordancia import gravar_pauta_desempate

    rotulos = {
        "avaliador_1": ["positivo", "positivo"],
        "avaliador_2": ["negativo", "positivo"],
        "avaliador_3": ["neutro", "positivo"],
    }
    escrever_trio(tmp_path, rotulos)
    resultado, por_avaliador = executar(tmp_path, normalizar=False)

    destino = tmp_path / "desempate.xlsx"
    gravar_pauta_desempate(resultado, por_avaliador, destino)

    aba = load_workbook(destino)["desempate"]
    cabecalho = [celula.value for celula in aba[1]]
    assert list(AVALIADORES) == cabecalho[2:5]
    assert aba.cell(row=2, column=1).value == 1
    assert [aba.cell(row=2, column=coluna).value for coluna in (3, 4, 5)] == [
        "positivo",
        "negativo",
        "neutro",
    ]


def test_gabarito_nao_inclui_empate(tmp_path):
    rotulos = {
        "avaliador_1": ["positivo"],
        "avaliador_2": ["negativo"],
        "avaliador_3": ["neutro"],
    }
    escrever_trio(tmp_path, rotulos)
    resultado, _ = executar(tmp_path, normalizar=False)

    assert resultado.gabarito == {}
    assert resultado.empates == [1]
    assert not resultado.atingiu_meta


def test_kappa_degenerado_nao_vira_zero(tmp_path):
    """Todos marcaram 'neutro' em tudo: concordancia total, mas Kappa indefinido.

    Devolver 0,0 aqui seria lido como 'discordaram completamente' — o oposto do fato.
    """
    rotulos = {
        avaliador: ["neutro", "neutro", "neutro"]
        for avaliador in AVALIADORES
    }
    escrever_trio(tmp_path, rotulos)

    resultado, _ = executar(tmp_path, normalizar=False)

    assert resultado.fleiss is None
    assert resultado.degenerado is not None
    assert not resultado.atingiu_meta
    assert len(resultado.gabarito) == 3


def test_apurar_conta_distribuicao_de_cada_avaliador(tmp_path):
    rotulos = {
        "avaliador_1": ["positivo", "positivo", "neutro"],
        "avaliador_2": ["positivo", "neutro", "neutro"],
        "avaliador_3": ["negativo", "negativo", "negativo"],
    }
    escrever_trio(tmp_path, rotulos)
    resultado, _ = executar(tmp_path, normalizar=False)

    assert resultado.distribuicao_por_avaliador["avaliador_1"]["positivo"] == 2
    assert resultado.distribuicao_por_avaliador["avaliador_3"]["negativo"] == 3


def test_cohen_par_a_par_detecta_o_avaliador_que_destoa(tmp_path):
    """1 e 2 iguais; 3 inverte tudo. O Fleiss geral esconde isso; o Cohen aponta."""
    rotulos = {
        "avaliador_1": ["positivo", "neutro", "negativo", "positivo", "neutro", "negativo"],
        "avaliador_2": ["positivo", "neutro", "negativo", "positivo", "neutro", "negativo"],
        "avaliador_3": ["negativo", "positivo", "neutro", "negativo", "positivo", "neutro"],
    }
    escrever_trio(tmp_path, rotulos)
    resultado, _ = executar(tmp_path, normalizar=False)

    assert resultado.cohen_por_par["avaliador_1 x avaliador_2"] == pytest.approx(1.0)
    assert resultado.cohen_por_par["avaliador_1 x avaliador_3"] < 0
    assert resultado.cohen_por_par["avaliador_2 x avaliador_3"] < 0


def test_resultado_calcula_a_media_de_cohen():
    resultado = apurar(_trio_simples(), [1, 2, 3, 4])
    assert len(resultado.cohen_por_par) == 3
    assert resultado.cohen_medio == pytest.approx(sum(resultado.cohen_por_par.values()) / 3)


def _trio_simples():
    """Tres avaliadores sobre 4 comentarios, montados em memoria (sem planilha)."""
    from ml.concordancia.calcular_concordancia import Resposta

    rotulos = {
        "avaliador_1": ["positivo", "neutro", "negativo", "positivo"],
        "avaliador_2": ["positivo", "neutro", "negativo", "neutro"],
        "avaliador_3": ["positivo", "negativo", "negativo", "positivo"],
    }
    return {
        avaliador: [
            Resposta(id_comentario, f"c{id_comentario}", rotulo, False, "", id_comentario + 1)
            for id_comentario, rotulo in enumerate(lista, start=1)
        ]
        for avaliador, lista in rotulos.items()
    }


def test_nan_nunca_sai_do_calculo():
    """Blindagem: Kappa NaN passaria pela comparacao com a meta sem estourar."""
    resultado = apurar(_trio_simples(), [1, 2, 3, 4])
    assert resultado.fleiss is not None
    assert not math.isnan(resultado.fleiss)
    assert all(not math.isnan(valor) for valor in resultado.cohen_por_par.values())
