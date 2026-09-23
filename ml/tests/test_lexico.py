"""Testes do classificador léxico.

Nada toca o banco e **nada depende do SentiLex real estar baixado**: os testes montam
léxicos minúsculos no formato publicado. O arquivo de verdade tem 6,9 MB, é dado de
terceiros e não é versionado — um teste que dependesse dele quebraria em máquina
recém-clonada, que é exatamente onde ele precisa passar.

Os casos de formato saem do recurso publicado, com as linhas reais: o verbo de
julgamento (`POL:N0=0` com `POL:N1=1`), o erro de digitação (`POL:N0=7`), a expressão
idiomática e o lema repetido em duas classes gramaticais.
"""

import pytest

from ml.config import CLASSES
from ml.lexico.sentilex import (
    NEGATIVO,
    NEUTRO,
    POSITIVO,
    Lexico,
    carregar,
    classificar,
    classificar_muitos,
    normalizar_chave,
    tokenizar,
)

# Linhas REAIS do SentiLex-flex-PT02, escolhidas uma a uma pelo que cada uma exercita.
FLEX = """\
ótima,ótimo.PoS=Adj;FLEX=fs;TG=HUM:N0;POL:N0=1;ANOT=JALC
péssimo,péssimo.PoS=Adj;FLEX=ms;TG=HUM:N0;POL:N0=-1;ANOT=JALC
más,mau.PoS=Adj;FLEX=fp;TG=HUM:N0;POL:N0=-1;ANOT=MAN
adorei,adorar.PoS=V;Flex=J:1s;TG=HUM:N0:N1;POL:N0=0;POL:N1=1;ANOT=MAN
abandonou,abandonar.PoS=V;Flex=J:3s;TG=HUM:N0:N1;POL:N0=-1;POL:N1=0;ANOT=MAN
abarcante,abarcante.PoS=Adj;FLEX=ms;TG=HUM:N0;POL:N0=0;ANOT=MAN;REV=POL
intrépido,intrépido.PoS=Adj;FLEX=ms;TG=HUM:N0;POL:N0=7;ANOT=MAN;REV=POL
abrir o coração,abrir o coração.PoS=IDIOM;TG=HUM:N0;POL:N0=1;ANOT=MAN
abatido,abatido.PoS=Adj;FLEX=ms;TG=HUM:N0;POL:N0=-1;ANOT=JALC
abatido,abater.PoS=V;Flex=PP;TG=HUM:N0:N1;POL:N0=1;POL:N1=-1;ANOT=MAN
"""

LEM = """\
à-vontade.PoS=N;TG=HUM:N0;POL:N0=1;ANOT=MAN
abafado.PoS=Adj;TG=HUM:N0;POL:N0=-1;ANOT=JALC
ser culpa de.PoS=IDIOM;TG=HUM:N1;POL:N1=-1;ANOT=MAN
"""


@pytest.fixture
def lexico(tmp_path):
    """O léxico de dez linhas, carregado do disco como o real seria."""
    caminho = tmp_path / "SentiLex-flex-PT02.txt"
    caminho.write_text(FLEX, encoding="utf-8")
    return carregar(caminho)


# ------------------------------------------------------------------ leitura do recurso


def test_le_o_formato_flex_e_indexa_pela_forma_flexionada(lexico):
    """No `flex` a chave é a forma ("adorei"), não o lema ("adorar")."""
    assert lexico.polaridade("adorei") == 1
    assert lexico.polaridade("adorar") is None


def test_le_o_formato_lem(tmp_path):
    caminho = tmp_path / "SentiLex-lem-PT02.txt"
    caminho.write_text(LEM, encoding="utf-8")
    lexico = carregar(caminho)

    assert lexico.polaridade("abafado") == -1
    assert lexico.polaridade("à-vontade") == 1


def test_expressao_idiomatica_fica_de_fora_e_e_contada(lexico):
    """666 idiomatismos do recurso não casam com busca palavra a palavra."""
    assert lexico.polaridade("abrir") is None
    assert lexico.descartes["multipalavra"] == 1


def test_polaridade_fora_da_escala_e_descartada_nao_corrigida(lexico):
    """`POL:N0=7` é erro de digitação do recurso publicado — somar 7 seria pior."""
    assert lexico.polaridade("intrépido") is None
    assert lexico.descartes["polaridade_invalida"] == 1


def test_grafia_repetida_com_polaridades_opostas_sai_do_indice(lexico):
    """"abatido" é -1 como adjetivo e +1 como particípio: a regra simples não escolhe."""
    assert lexico.polaridade("abatido") is None
    assert lexico.descartes["colisao_de_chave"] == 1


def test_zero_declarado_continua_no_indice(lexico):
    """`POL:N0=0` é polaridade declarada, não ausência: a palavra é conhecida."""
    assert lexico.polaridade("abarcante") == 0


def test_verbo_de_julgamento_usa_a_polaridade_do_complemento(lexico):
    """"adorar" traz N0=0 e N1=1: quem adora não é julgado, o adorado sai bem.

    Sem esta cláusula "adorei o comercial" seria invisível para o piso — o erro que
    mais barato passa despercebido em avaliação de léxico.
    """
    assert lexico.polaridade("adorei") == 1
    assert lexico.entradas_por_complemento == 1


def test_polaridade_do_sujeito_nunca_e_sobrescrita_pela_do_complemento(lexico):
    """"abandonar" declara -1 no sujeito: o complemento (0) não apaga isso."""
    assert lexico.polaridade("abandonou") == -1


def test_registra_arquivo_e_hash_para_reprodutibilidade(lexico):
    assert lexico.arquivo == "SentiLex-flex-PT02.txt"
    assert len(lexico.sha256) == 64
    assert lexico.entradas_lidas == 10


# ---------------------------------------------------------------- chave e tokenização


def test_chave_ignora_maiuscula_mas_preserva_acento():
    assert normalizar_chave("ÓTIMA") == "ótima"
    assert normalizar_chave("Adorei") == "adorei"


def test_mas_nao_casa_com_mas_acentuado(lexico):
    """Regressão da decisão medida: ignorar acento faria "mas" valer -1.

    No conjunto de teste isso aconteceria 17 vezes — contra quatro ganhos legítimos.
    A conjunção mais comum do português não pode entrar como palavra negativa.
    """
    assert lexico.polaridade("más") == -1
    assert lexico.polaridade("mas") is None
    assert classificar("bom, mas caro", lexico).rotulo != NEGATIVO


def test_tokenizar_separa_pontuacao_e_mantem_hifen():
    assert tokenizar("Adorei!! O produto, serio :)") == ["Adorei", "O", "produto", "serio"]
    assert tokenizar("fiquei à-vontade") == ["fiquei", "à-vontade"]
    assert tokenizar("nota 10 de 10") == ["nota", "de"]


# --------------------------------------------------------------------- regra de soma


def test_soma_positiva_vira_positivo(lexico):
    previsao = classificar("que ótima propaganda, adorei", lexico)
    assert previsao.rotulo == POSITIVO
    assert previsao.escore == 2
    assert previsao.positivos == 2


def test_soma_negativa_vira_negativo(lexico):
    previsao = classificar("péssimo, a marca abandonou o cliente", lexico)
    assert previsao.rotulo == NEGATIVO
    assert previsao.escore == -2
    assert previsao.negativos == 2


def test_empate_vira_neutro_e_isso_e_diferente_de_nao_achar_nada(lexico):
    """Os dois caminhos para `neutro` precisam ser distinguíveis no relatório."""
    empate = classificar("ótima ideia, execução péssimo", lexico)
    vazio = classificar("vi o anuncio ontem na tv", lexico)

    assert empate.rotulo == vazio.rotulo == NEUTRO
    assert empate.cobriu is True
    assert vazio.cobriu is False
    assert vazio.escore == 0


def test_palavra_repetida_conta_todas_as_vezes(lexico):
    """Somar repetição é a regra mínima; tirá-la já seria heurística."""
    assert classificar("péssimo péssimo péssimo", lexico).escore == -3


def test_texto_vazio_nao_estoura(lexico):
    previsao = classificar("", lexico)
    assert previsao.rotulo == NEUTRO
    assert previsao.termos == ()


def test_previsao_guarda_o_rastro_das_palavras(lexico):
    """A explicabilidade é a única vantagem real do léxico sobre o BERTimbau."""
    previsao = classificar("ótima entrega, péssimo suporte", lexico)
    assert previsao.termos == (("ótima", 1), ("péssimo", -1))


def test_classificar_muitos_preserva_a_ordem(lexico):
    previsoes = classificar_muitos(["ótima", "péssimo", "nada aqui"], lexico)
    assert [previsao.rotulo for previsao in previsoes] == [POSITIVO, NEGATIVO, NEUTRO]


# ------------------------------------------------------------------------- contratos


def test_rotulos_batem_com_os_do_projeto():
    """`sentilex` não importa `ml.config` (precisa virar fallback do worker).

    O preço de repetir os três rótulos é este teste, que impede a cópia de divergir
    do CHECK do banco.
    """
    assert set(CLASSES) == {POSITIVO, NEGATIVO, NEUTRO}


def test_entra_o_texto_do_modelo_e_o_emoji_convertido_e_visivel(lexico):
    """A entrada é `preparar_texto`, e é isso que faz o léxico enxergar emoji.

    Sem o pré-processamento compartilhado, 😍 seria pontuação para a regra de soma.
    Com ele vira "amei" — e no SentiLex real onze palavras do mapa de emoji têm
    polaridade ("amei", "raiva", "choro", "lixo", "maravilhoso"...).
    """
    from preprocessamento import preparar_texto

    pequeno = Lexico({"amei": 1}, "sintetico", "", 1)
    assert classificar(preparar_texto("demais \U0001f60d"), pequeno).rotulo == POSITIVO
