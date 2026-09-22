"""Testes do pré-processamento compartilhado.

Sem rede e sem banco: é stdlib pura, e roda igual nos dois ambientes (ml/ e backend/).
"""

import pytest

from preprocessamento import (
    VERSAO,
    converter_emoji,
    normalizar_espacos,
    normalizar_tipografia,
    preparar_texto,
)

# --------------------------------------------------------------------- espaços


def test_quebra_de_linha_vira_espaco():
    assert normalizar_espacos("linha um\nlinha dois") == "linha um linha dois"
    assert normalizar_espacos("windows\r\nunix\rmac") == "windows unix mac"


def test_espaco_em_excesso_e_colapsado():
    assert normalizar_espacos("  muito    espaço  ") == "muito espaço"


def test_texto_so_com_espaco_vira_vazio():
    assert preparar_texto("   \n\t  ") == ""
    assert preparar_texto("") == ""


# ----------------------------------------------------------------------- emoji


def test_emoji_do_mapa_vira_a_palavra_curada():
    assert preparar_texto("que engraçado 😂") == "que engraçado risos"
    assert preparar_texto("❤ demais") == "coração demais"
    assert preparar_texto("👏👏👏") == "aplausos aplausos aplausos"


def test_emoji_colado_na_palavra_nao_gruda():
    """Sem o espaço injetado, `top😂` viraria `toprisos` e o tokenizer se perderia."""
    assert preparar_texto("top😂") == "top risos"
    assert preparar_texto("bom👍dia") == "bom positivo dia"


def test_bandeira_do_brasil_e_tratada_como_sequencia():
    """🇧🇷 são DOIS indicadores regionais; separados não querem dizer Brasil."""
    assert preparar_texto("orgulho 🇧🇷") == "orgulho bandeira do Brasil"


def test_invisiveis_somem_sem_virar_palavra():
    """Seletor de variação e tom de pele não têm significado sozinhos."""
    assert preparar_texto("❤️") == "coração"
    assert preparar_texto("👏\U0001f3fb") == "aplausos"
    # ZWJ emenda emoji compostos; cada parte é convertida por si
    assert "emoji" not in preparar_texto("❤️")


def test_emoji_fora_do_mapa_cai_na_classificacao_automatica():
    """A cauda longa não pode voltar a virar [UNK]: recebe rótulo grosseiro."""
    assert preparar_texto("🫠") != ""
    assert preparar_texto("💛") == "coração"  # HEART no nome Unicode
    assert preparar_texto("🦾") == "mão"  # MECHANICAL ARM
    assert preparar_texto("🏁") == "bandeira"  # CHEQUERED FLAG
    assert preparar_texto("🫠") == "rosto"  # MELTING FACE


def test_classificacao_casa_por_palavra_e_nao_por_substring():
    """ "ARM" dentro de "ALARM CLOCK" nao pode fazer um despertador virar "mao"."""
    assert preparar_texto("⏰") == "emoji"
    assert preparar_texto("💛") == "coração"  # YELLOW HEART, casa a palavra HEART


def test_emoji_sem_nome_unicode_nao_quebra():
    """Emoji mais novo que a tabela do Python não pode levantar exceção."""
    resultado = preparar_texto("nota \U0001fa75 boa")
    assert resultado.startswith("nota ")
    assert resultado.endswith(" boa")
    assert "\U0001fa75" not in resultado


def test_nenhum_emoji_sobrevive_a_conversao():
    """Invariante central: depois de preparar_texto não resta pictograma nenhum."""
    from preprocessamento import e_emoji

    entrada = "😂❤👏💿🥤🎉🙏😮🇧🇷🔥✅🤩😭💩☠🤔\U0001fa75🫠"
    saida = preparar_texto(entrada)
    assert not any(e_emoji(c) for c in saida), f"sobrou emoji em {saida!r}"


# --------------------------------------------------------------- determinismo


def test_conversao_e_idempotente_no_resultado():
    """Reaplicar em texto já preparado não muda mais nada."""
    uma_vez = preparar_texto("amei 😂😂 demais ❤")
    duas_vezes = preparar_texto(uma_vez)
    assert uma_vez == duas_vezes


def test_texto_sem_emoji_so_perde_espaco():
    original = "Produto  bom,\nmas caro."
    assert preparar_texto(original) == "Produto bom, mas caro."


def test_converter_emoji_nao_mexe_em_texto_comum():
    assert converter_emoji("abc 123 ção!") == "abc 123 ção!"


# ------------------------------------------------------------------ tipografia


def test_reticencias_viram_tres_pontos():
    """… é um caractere só e não está no vocabulário; "..." está."""
    assert normalizar_tipografia("esperando…") == "esperando..."
    assert preparar_texto("ate quando…") == "ate quando..."


def test_acento_agudo_usado_como_apostrofo():
    assert normalizar_tipografia("Assassin´s Creed") == "Assassin's Creed"
    assert preparar_texto("joguei Assassin´s") == "joguei Assassin's"


def test_giria_nao_e_expandida():
    """CLAUDE.md Seção 10: expandir gíria é normalização SEMÂNTICA, proibida aqui.

    O avaliador humano lê "q" e entende "que" sem que ninguém reescreva por ele;
    o pipeline não pode interpretar no lugar dele.
    """
    assert preparar_texto("q bom") == "q bom"
    assert preparar_texto("qnd chega") == "qnd chega"
    assert preparar_texto("vc eh mto bom") == "vc eh mto bom"


# ------------------------------------------------- canonico vs. texto do modelo


def test_normalizar_espacos_nao_altera_conteudo():
    """O texto canônico (banco, humano, Gemini) só perde espaço — mais nada."""
    assert normalizar_espacos("amei 😂😂") == "amei 😂😂"
    assert normalizar_espacos("esperando…") == "esperando…"
    assert normalizar_espacos("Assassin´s") == "Assassin´s"


def test_preparar_texto_e_o_unico_que_converte():
    """A diferença entre os dois é exatamente o que o BERTimbau não consegue ler."""
    original = "amei 😂 esperando…"
    assert normalizar_espacos(original) == "amei 😂 esperando…"
    assert preparar_texto(original) == "amei risos esperando..."


# ------------------------------------------------------------------- contrato


def test_versao_exposta_para_o_model_card():
    """O model_card.json grava esta versão; sem ela não dá para detectar skew."""
    assert VERSAO
    assert VERSAO.count(".") == 2


def test_versao_bate_com_o_pyproject():
    """Duas fontes da mesma verdade não podem divergir em silêncio."""
    import pathlib
    import re

    pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
    declarada = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    assert declarada, "version não encontrada no pyproject.toml"
    assert declarada.group(1) == VERSAO


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("😂", "risos"),
        ("😭", "choro"),
        ("😠", "raiva"),
        ("👍", "positivo"),
        ("👎", "negativo"),
    ],
)
def test_sentimento_e_preservado_nas_palavras_escolhidas(entrada: str, esperado: str):
    """A tradução carrega sentimento, não a descrição do desenho."""
    assert preparar_texto(entrada) == esperado
