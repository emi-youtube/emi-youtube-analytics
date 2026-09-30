"""Testes do classificador BERTimbau, do download dos pesos e da contingência léxica.

**Nenhum teste baixa nem carrega o modelo de verdade** (~420 MB). O que está sob teste
é a costura, não o conteúdo dos pesos:

- a conferência de integridade e a leitura do cartão usam uma pasta sintética;
- o carregamento com `transformers` usa um BERT **minúsculo** (uma camada, oito
  dimensões, vocabulário de vinte tokens), montado e salvo em `tmp_path` na hora —
  mesmo formato de pasta que o Colab exporta, pesos aleatórios;
- o download usa `httpx.MockTransport`: nenhuma requisição sai da máquina.

O teste com o modelo real existe, mas só roda com `EMI_TESTE_MODELO_REAL=1` e a pasta
presente — é verificação local, não de CI.
"""

import hashlib
import json
import logging
import os

import httpx
import pytest
from preprocessamento import VERSAO as VERSAO_PREPROCESSAMENTO
from sqlalchemy import select

from app.core.config import settings
from app.inferencia import bertimbau as modulo_bertimbau
from app.inferencia import lexico as lexico_producao
from app.inferencia.baixar_bertimbau import baixar
from app.inferencia.base import SENTIMENTOS_VALIDOS, ClassificadorIndisponivel
from app.inferencia.bertimbau import (
    ClassificadorBertimbau,
    conferir_pasta,
    formatar_confianca,
    ler_manifesto,
)
from app.inferencia.lexico import ClassificadorLexico
from app.models.analise_sentimento import AnaliseSentimento
from app.models.versao_modelo import VersaoModelo
from app.workers import inferencia, runner
from tests.test_worker_inferencia import (
    LEXICO_SINTETICO,
    enfileirar_inferencia,
    montar_execucao_com_comentarios,
    sha256_do,
)

NOME = "bertimbau-teste"
VERSAO = "0.0.1-teste"
ID2LABEL = {"0": "positivo", "1": "negativo", "2": "neutro"}


def cartao_sintetico(**extras) -> dict:
    cartao = {
        "versao_cartao": "1.0",
        "nome_modelo": NOME,
        "versao": VERSAO,
        "modelo_base": "minusculo-de-teste",
        "id2label": ID2LABEL,
        "label2id": {rotulo: int(indice) for indice, rotulo in ID2LABEL.items()},
        "max_length": 16,
        "versao_preprocessamento": VERSAO_PREPROCESSAMENTO,
        "semente": 42,
        "dados": {"fonte": "sintetico"},
        "avaliacao_gabarito_humano": {"f1_macro": 0.5},
    }
    cartao.update(extras)
    return cartao


def manifesto_da_pasta(pasta) -> dict:
    """O manifesto que a pasta TEM — o que o `bertimbau_manifesto.json` seria para ela."""
    return {
        "nome_modelo": NOME,
        "versao": VERSAO,
        "arquivos": {
            arquivo.name: hashlib.sha256(arquivo.read_bytes()).hexdigest()
            for arquivo in sorted(pasta.iterdir())
            if arquivo.is_file()
        },
    }


def escrever_cartao(pasta, cartao: dict) -> None:
    (pasta / "model_card.json").write_text(json.dumps(cartao), encoding="utf-8")


# --------------------------------------------------------------- modelo minúsculo


@pytest.fixture(scope="module")
def pasta_modelo_minusculo(tmp_path_factory):
    """Um BERT de verdade, só que minúsculo, salvo no formato que o Colab exporta."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")

    pasta = tmp_path_factory.mktemp("bertimbau-minusculo")
    vocabulario = [
        "[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]",
        "adorei", "odiei", "o", "produto", "caro", "bom", "ruim", "emoji", "!", ".",
        "muito", "nada", "achei", "normal", "chegou",
    ]  # fmt: skip
    (pasta / "vocab.txt").write_text("\n".join(vocabulario), encoding="utf-8")
    tokenizador = transformers.BertTokenizerFast(
        vocab_file=str(pasta / "vocab.txt"), do_lower_case=False
    )
    tokenizador.save_pretrained(pasta)

    torch.manual_seed(42)
    configuracao = transformers.BertConfig(
        vocab_size=len(vocabulario),
        hidden_size=8,
        num_hidden_layers=1,
        num_attention_heads=1,
        intermediate_size=8,
        max_position_embeddings=32,
        num_labels=3,
        id2label={int(indice): rotulo for indice, rotulo in ID2LABEL.items()},
        label2id={rotulo: int(indice) for indice, rotulo in ID2LABEL.items()},
    )
    transformers.BertForSequenceClassification(configuracao).save_pretrained(pasta)
    escrever_cartao(pasta, cartao_sintetico())
    return pasta


@pytest.fixture
def modelo_minusculo(pasta_modelo_minusculo):
    return ClassificadorBertimbau.de_pasta(
        pasta_modelo_minusculo, manifesto_da_pasta(pasta_modelo_minusculo)
    )


def test_carrega_o_modelo_e_classifica(modelo_minusculo):
    classificacao = modelo_minusculo.classificar("adorei o produto")

    assert classificacao.sentimento in SENTIMENTOS_VALIDOS
    assert classificacao.justificativa.startswith("confiança do modelo: ")


def test_classificacao_e_deterministica(modelo_minusculo):
    """`eval()` desliga o dropout: o mesmo texto não pode mudar de rótulo entre chamadas."""
    primeira = modelo_minusculo.classificar("achei caro")
    assert all(modelo_minusculo.classificar("achei caro") == primeira for _ in range(3))


def test_descritor_vem_do_cartao_e_nao_do_lexico(modelo_minusculo, pasta_modelo_minusculo):
    descritor = modelo_minusculo.descritor

    assert (descritor.nome_modelo, descritor.versao) == (NOME, VERSAO)
    assert descritor.nome_modelo != lexico_producao.NOME_MODELO
    proveniencia = descritor.proveniencia
    assert proveniencia["sha256_arquivos"] == manifesto_da_pasta(pasta_modelo_minusculo)["arquivos"]
    assert proveniencia["avaliacao_gabarito_humano"] == {"f1_macro": 0.5}
    assert proveniencia["id2label"] == ID2LABEL


def test_texto_longo_e_truncado_no_max_length_do_cartao(modelo_minusculo):
    """128 tokens no treino; mais que isso nunca chega ao modelo (aqui, 16)."""
    classificacao = modelo_minusculo.classificar(" ".join(["muito"] * 500))
    assert classificacao.sentimento in SENTIMENTOS_VALIDOS


def test_numero_de_saidas_diferente_do_cartao_e_recusado(pasta_modelo_minusculo, tmp_path):
    """Modelo de 3 saídas com cartão de 2 rótulos: a ordem não teria como bater."""
    pasta = tmp_path / "modelo"
    pasta.mkdir()
    for arquivo in pasta_modelo_minusculo.iterdir():
        (pasta / arquivo.name).write_bytes(arquivo.read_bytes())
    escrever_cartao(pasta, cartao_sintetico(id2label={"0": "positivo", "1": "negativo"}))

    with pytest.raises(ClassificadorIndisponivel, match="saidas"):
        ClassificadorBertimbau.de_pasta(pasta, manifesto_da_pasta(pasta))


# ------------------------------------------------------- classificar sem torch


def classificador_com(probabilidades, id2label=None) -> ClassificadorBertimbau:
    """O classificador com o preditor substituído: testa a tradução, não o modelo."""
    cartao = cartao_sintetico(id2label=id2label or ID2LABEL)
    return ClassificadorBertimbau(lambda _texto: probabilidades, cartao, {"metodo": "teste"})


def test_rotulo_e_a_classe_de_maior_probabilidade():
    assert classificador_com([0.1, 0.7, 0.2]).classificar("x").sentimento == "negativo"


def test_ordem_dos_rotulos_vem_do_cartao_e_nao_do_codigo():
    """CLAUDE.md regra 5: o mesmo vetor, com outro id2label, é outro rótulo."""
    outra_ordem = {"0": "neutro", "1": "positivo", "2": "negativo"}
    assert classificador_com([0.1, 0.7, 0.2], outra_ordem).classificar("x").sentimento == (
        "positivo"
    )


def test_justificativa_mostra_as_tres_classes_da_maior_para_a_menor():
    justificativa = classificador_com([0.04, 0.02, 0.94]).classificar("x").justificativa
    assert justificativa == "confiança do modelo: neutro 94% · positivo 4% · negativo 2%"


def test_formatar_confianca_arredonda_para_inteiro():
    texto = formatar_confianca({"positivo": 0.505, "negativo": 0.2949, "neutro": 0.2001})
    assert texto == "confiança do modelo: positivo 50% · negativo 29% · neutro 20%"


def test_preditor_com_numero_errado_de_saidas_falha_alto():
    with pytest.raises(ValueError, match="saidas"):
        classificador_com([0.5, 0.5]).classificar("x")


def test_portao_do_preprocessamento_usa_a_versao_do_cartao():
    """Regra 5: o modelo foi TREINADO com a versão do cartão; divergir é recusar."""
    cartao = cartao_sintetico(versao_preprocessamento="0.0.0")
    classificador = ClassificadorBertimbau(lambda _t: [1, 0, 0], cartao, {})

    assert classificador.versao_preprocessamento == "0.0.0"
    with pytest.raises(ClassificadorIndisponivel, match="preprocessamento"):
        classificador.validar()


# ------------------------------------------------------------- integridade


@pytest.fixture
def pasta_sintetica(tmp_path):
    """Pasta com arquivos de mentira: o suficiente para conferir hash e cartão."""
    pasta = tmp_path / "modelo"
    pasta.mkdir()
    (pasta / "model.safetensors").write_bytes(b"pesos de mentira")
    (pasta / "vocab.txt").write_text("[PAD]\n[UNK]", encoding="utf-8")
    escrever_cartao(pasta, cartao_sintetico())
    return pasta


def test_pasta_ausente_falha_com_o_caminho_e_como_obter(tmp_path):
    ausente = tmp_path / "nao-existe"
    with pytest.raises(ClassificadorIndisponivel) as erro:
        conferir_pasta(ausente, {"arquivos": {}})
    assert str(ausente) in str(erro.value)
    assert "baixar_bertimbau" in str(erro.value)


def test_arquivo_ausente_e_listado(pasta_sintetica):
    manifesto = manifesto_da_pasta(pasta_sintetica)
    (pasta_sintetica / "vocab.txt").unlink()

    with pytest.raises(ClassificadorIndisponivel, match=r"ausente:\s+vocab.txt"):
        conferir_pasta(pasta_sintetica, manifesto)


def test_sha256_diferente_recusa_os_pesos(pasta_sintetica):
    manifesto = manifesto_da_pasta(pasta_sintetica)
    (pasta_sintetica / "model.safetensors").write_bytes(b"outros pesos")

    with pytest.raises(ClassificadorIndisponivel, match=r"sha256 diferente: model.safetensors"):
        conferir_pasta(pasta_sintetica, manifesto)


def test_cartao_de_outra_versao_e_recusado(pasta_sintetica):
    escrever_cartao(pasta_sintetica, cartao_sintetico(versao="0.1.0-ensaio"))
    manifesto = manifesto_da_pasta(pasta_sintetica)  # hash confere; a identidade não

    with pytest.raises(ClassificadorIndisponivel, match="manifesto"):
        ClassificadorBertimbau.de_pasta(pasta_sintetica, manifesto)


def test_rotulo_fora_do_check_do_banco_e_recusado(pasta_sintetica):
    escrever_cartao(
        pasta_sintetica,
        cartao_sintetico(id2label={"0": "positivo", "1": "negativo", "2": "misto"}),
    )
    with pytest.raises(ClassificadorIndisponivel, match="misto"):
        ClassificadorBertimbau.de_pasta(pasta_sintetica, manifesto_da_pasta(pasta_sintetica))


def test_cartao_sem_campo_obrigatorio_e_recusado(pasta_sintetica):
    cartao = cartao_sintetico()
    del cartao["max_length"]
    escrever_cartao(pasta_sintetica, cartao)

    with pytest.raises(ClassificadorIndisponivel, match="max_length"):
        ClassificadorBertimbau.de_pasta(pasta_sintetica, manifesto_da_pasta(pasta_sintetica))


def test_manifesto_versionado_e_o_do_modelo_oficial():
    """O manifesto do repositório descreve o 1.0.0, e cobre pesos, tokenizer e cartão."""
    manifesto = ler_manifesto()

    assert (manifesto["nome_modelo"], manifesto["versao"]) == ("bertimbau-emi", "1.0.0")
    assert {"model.safetensors", "model_card.json", "config.json", "tokenizer.json"} <= set(
        manifesto["arquivos"]
    )
    assert all(len(valor) == 64 for valor in manifesto["arquivos"].values())


# ----------------------------------------------------------------- download


def transporte_servindo(pasta, chamadas: list[str], corromper: str | None = None):
    """Um Hugging Face Hub de mentira que serve os arquivos da pasta."""

    def responder(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao.url.path)
        if requisicao.headers.get("Authorization") != "Bearer token-leitura":
            return httpx.Response(401)
        nome = requisicao.url.path.rsplit("/", 1)[-1]
        arquivo = pasta / nome
        if not arquivo.is_file():
            return httpx.Response(404)
        conteudo = arquivo.read_bytes()
        if nome == corromper:
            conteudo = conteudo[: len(conteudo) // 2]
        return httpx.Response(200, content=conteudo)

    return httpx.MockTransport(responder)


def test_baixa_confere_e_promove(pasta_sintetica, tmp_path):
    manifesto = manifesto_da_pasta(pasta_sintetica)
    destino = tmp_path / "destino"
    chamadas: list[str] = []

    with httpx.Client(transport=transporte_servindo(pasta_sintetica, chamadas)) as cliente:
        problemas = baixar(destino, "org/repo", "abc123", "token-leitura", cliente, manifesto)

    assert problemas == []
    assert manifesto_da_pasta(destino)["arquivos"] == manifesto["arquivos"]
    assert all(caminho.startswith("/org/repo/resolve/abc123/") for caminho in chamadas)
    assert not list(destino.glob("*.parcial"))


def test_arquivo_ja_conferido_nao_e_baixado_de_novo(pasta_sintetica, tmp_path):
    manifesto = manifesto_da_pasta(pasta_sintetica)
    destino = tmp_path / "destino"
    destino.mkdir()
    (destino / "model.safetensors").write_bytes(b"pesos de mentira")
    chamadas: list[str] = []

    with httpx.Client(transport=transporte_servindo(pasta_sintetica, chamadas)) as cliente:
        baixar(destino, "org/repo", "main", "token-leitura", cliente, manifesto)

    assert not any(caminho.endswith("model.safetensors") for caminho in chamadas)


def test_download_truncado_nao_vira_arquivo_definitivo(pasta_sintetica, tmp_path):
    """sha256 errado: o `.parcial` é apagado e o nome definitivo nunca aparece."""
    manifesto = manifesto_da_pasta(pasta_sintetica)
    destino = tmp_path / "destino"
    transporte = transporte_servindo(pasta_sintetica, [], corromper="model.safetensors")

    with httpx.Client(transport=transporte) as cliente:
        problemas = baixar(destino, "org/repo", "main", "token-leitura", cliente, manifesto)

    assert problemas == ["model.safetensors"]
    assert not (destino / "model.safetensors").exists()
    assert not list(destino.glob("*.parcial"))


def test_token_errado_falha_sem_vazar_o_token_no_log(pasta_sintetica, tmp_path, caplog):
    manifesto = manifesto_da_pasta(pasta_sintetica)
    with (
        caplog.at_level(logging.INFO),
        httpx.Client(transport=transporte_servindo(pasta_sintetica, [])) as cliente,
    ):
        problemas = baixar(tmp_path / "d", "org/repo", "main", "token-secreto", cliente, manifesto)

    assert set(problemas) == set(manifesto["arquivos"])
    assert "token-secreto" not in caplog.text


# ----------------------------------------------------- contingência: o léxico


@pytest.fixture
def lexico_disponivel(tmp_path, monkeypatch):
    """SentiLex sintético no caminho configurado, com o portão ensinado a aceitá-lo."""
    caminho = tmp_path / "SentiLex-flex-PT02.txt"
    caminho.write_text(LEXICO_SINTETICO, encoding="utf-8")
    monkeypatch.setattr(lexico_producao, "SHA256_ESPERADO", sha256_do(caminho))
    monkeypatch.setattr(settings, "sentilex_path", str(caminho))
    return caminho


def test_sem_a_pasta_do_bertimbau_o_worker_cai_para_o_lexico(
    lexico_disponivel, tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(settings, "bertimbau_path", str(tmp_path / "sem-modelo"))

    with caplog.at_level(logging.WARNING):
        classificador = runner.montar_classificador()

    assert isinstance(classificador, ClassificadorLexico)
    assert "contingencia" in caplog.text
    assert str(tmp_path / "sem-modelo") in caplog.text  # o motivo, não só o fato


def test_preprocessamento_divergente_tambem_cai_para_o_lexico(
    lexico_disponivel, pasta_sintetica, monkeypatch, caplog
):
    """O portão da regra 5 recusa o BERTimbau; a recusa é contingência, não queda."""
    escrever_cartao(pasta_sintetica, cartao_sintetico(versao_preprocessamento="0.0.0"))
    manifesto = manifesto_da_pasta(pasta_sintetica)
    monkeypatch.setattr(modulo_bertimbau, "ler_manifesto", lambda: manifesto)
    monkeypatch.setattr(settings, "bertimbau_path", str(pasta_sintetica))

    # Os pesos de mentira não carregam; o que se quer é que o portão rode ANTES.
    def carregar_sem_torch(pasta, _manifesto=None):
        modulo_bertimbau.conferir_pasta(pasta, manifesto)
        cartao = modulo_bertimbau.ler_cartao(pasta, manifesto)
        return ClassificadorBertimbau(lambda _t: [1, 0, 0], cartao, {})

    monkeypatch.setattr(ClassificadorBertimbau, "de_pasta", staticmethod(carregar_sem_torch))

    with caplog.at_level(logging.WARNING):
        classificador = runner.montar_classificador()

    assert isinstance(classificador, ClassificadorLexico)
    assert "preprocessamento" in caplog.text


def test_com_o_modelo_em_pe_o_worker_usa_o_bertimbau(
    lexico_disponivel, pasta_modelo_minusculo, monkeypatch
):
    manifesto = manifesto_da_pasta(pasta_modelo_minusculo)
    monkeypatch.setattr(modulo_bertimbau, "ler_manifesto", lambda: manifesto)
    monkeypatch.setattr(settings, "bertimbau_path", str(pasta_modelo_minusculo))

    assert isinstance(runner.montar_classificador(), ClassificadorBertimbau)


def test_sem_bertimbau_e_sem_lexico_o_worker_nao_sobe(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "bertimbau_path", str(tmp_path / "sem-modelo"))
    monkeypatch.setattr(settings, "sentilex_path", str(tmp_path / "sem-lexico.txt"))

    with pytest.raises(ClassificadorIndisponivel, match="SentiLex"):
        runner.montar_classificador()


async def test_analise_em_contingencia_aponta_para_a_versao_do_lexico(
    sessao, lexico_disponivel, tmp_path, monkeypatch
):
    """O histórico diz quem rotulou: em contingência, é o léxico, não o BERTimbau."""
    monkeypatch.setattr(settings, "bertimbau_path", str(tmp_path / "sem-modelo"))
    classificador = runner.montar_classificador()

    execucao = await montar_execucao_com_comentarios(sessao, ["produto ótimo", "caro"])
    await enfileirar_inferencia(sessao, execucao)
    assert await inferencia.executar_proximo(sessao, classificador)

    versoes = (
        await sessao.scalars(
            select(VersaoModelo.nome_modelo)
            .join(AnaliseSentimento, AnaliseSentimento.id_versao_modelo == VersaoModelo.id_versao)
            .distinct()
        )
    ).all()
    assert versoes == [lexico_producao.NOME_MODELO]


async def test_analise_do_bertimbau_aponta_para_a_versao_do_cartao(sessao, modelo_minusculo):
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei o produto", "odiei"])
    await enfileirar_inferencia(sessao, execucao)
    assert await inferencia.executar_proximo(sessao, modelo_minusculo)

    analises = (await sessao.scalars(select(AnaliseSentimento))).all()
    versao = await sessao.get(VersaoModelo, analises[0].id_versao_modelo)
    assert (versao.nome_modelo, versao.versao) == (NOME, VERSAO)
    assert versao.metricas_avaliacao["proveniencia"]["sha256_arquivos"]
    assert all(a.justificativa.startswith("confiança do modelo") for a in analises)


# ------------------------------------------------- modelo real: só local, opt-in


@pytest.mark.skipif(
    os.environ.get("EMI_TESTE_MODELO_REAL") != "1" or not settings.caminho_bertimbau.is_dir(),
    reason="modelo real so localmente: EMI_TESTE_MODELO_REAL=1 e a pasta presente",
)
def test_modelo_oficial_carrega_e_acerta_o_obvio():
    classificador = ClassificadorBertimbau.de_pasta(settings.caminho_bertimbau)
    classificador.validar()

    assert classificador.descritor.nome_modelo == "bertimbau-emi"
    assert classificador.classificar("Amei essa propaganda, muito boa!").sentimento == "positivo"
    assert classificador.classificar("Que propaganda horrível, péssima").sentimento == "negativo"
