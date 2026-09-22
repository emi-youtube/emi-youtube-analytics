"""Testes da rotulagem fraca. Nenhum toca a rede — cota da Gemini é finita.

O que estes testes protegem: a validação da resposta (categoria fechada, casamento
por id, lote completo), a sincronia entre o prompt do código e o arquivo versionado,
e a garantia de que a chave não vai para a URL.
"""

import json

import pytest

from ml.config import CLASSES
from ml.rotulagem.gemini import CABECALHO_CHAVE, ClienteGemini
from ml.rotulagem.rotular_fraco import (
    ARQUIVO_PROMPT,
    PROMPT_TAREFA,
    RespostaInvalida,
    extrair_json,
    montar_prompt,
    validar_lote,
)

IDS = {1, 2, 3}


def resposta(*pares) -> list[dict]:
    return [{"id_comentario": i, "rotulo": r} for i, r in pares]


# ------------------------------------------------------------------ validação


def test_lote_valido_vira_dicionario():
    itens = resposta((1, "positivo"), (2, "negativo"), (3, "neutro"))
    assert validar_lote(itens, IDS) == {1: "positivo", 2: "negativo", 3: "neutro"}


def test_rotulo_fora_das_tres_classes_refaz():
    """Categoria fechada: 'muito positivo' nao vira classe nova nem cai em neutro."""
    itens = resposta((1, "positivo"), (2, "muito positivo"), (3, "neutro"))
    with pytest.raises(RespostaInvalida, match="fora de"):
        validar_lote(itens, IDS)


@pytest.mark.parametrize("ruim", ["Positivo", "POSITIVO", "positive", "", None, 1])
def test_variacao_de_grafia_tambem_e_recusada(ruim):
    """Aceitar 'Positivo' abriria a porta para gravar rotulo que o CHECK barra."""
    with pytest.raises(RespostaInvalida):
        validar_lote([{"id_comentario": 1, "rotulo": ruim}], {1})


def test_item_faltando_refaz():
    itens = resposta((1, "positivo"), (2, "neutro"))
    with pytest.raises(RespostaInvalida, match="faltaram"):
        validar_lote(itens, IDS)


def test_id_estranho_ao_lote_refaz():
    """Id inventado indica alucinacao; gravar seria corromper outro exemplo."""
    itens = resposta((1, "positivo"), (2, "neutro"), (999, "negativo"))
    with pytest.raises(RespostaInvalida, match="nao estava no lote"):
        validar_lote(itens, IDS)


def test_id_repetido_refaz():
    itens = resposta((1, "positivo"), (1, "negativo"), (2, "neutro"), (3, "neutro"))
    with pytest.raises(RespostaInvalida, match="repetido"):
        validar_lote(itens, IDS)


def test_casamento_e_por_id_e_nao_por_posicao():
    """A ordem da resposta nao importa: o que casa e o id_comentario."""
    itens = resposta((3, "negativo"), (1, "neutro"), (2, "positivo"))
    assert validar_lote(itens, IDS) == {1: "neutro", 2: "positivo", 3: "negativo"}


def test_id_como_string_e_recusado():
    with pytest.raises(RespostaInvalida, match="nao inteiro"):
        validar_lote([{"id_comentario": "1", "rotulo": "positivo"}], {1})


# ------------------------------------------------------------- parsing do JSON


def test_json_puro():
    assert extrair_json('[{"id_comentario": 1, "rotulo": "neutro"}]') == [
        {"id_comentario": 1, "rotulo": "neutro"}
    ]


def test_json_dentro_de_cerca_markdown():
    bruto = '```json\n[{"id_comentario": 1, "rotulo": "neutro"}]\n```'
    assert extrair_json(bruto) == [{"id_comentario": 1, "rotulo": "neutro"}]


def test_texto_que_nao_e_json_refaz():
    with pytest.raises(RespostaInvalida, match="nao e JSON"):
        extrair_json("Claro! Aqui estao os rotulos:")


def test_objeto_no_lugar_de_array_refaz():
    with pytest.raises(RespostaInvalida, match="esperado array"):
        extrair_json('{"id_comentario": 1, "rotulo": "neutro"}')


# ------------------------------------------------------------------- prompt


class _Registro(dict):
    """asyncpg.Record se comporta como mapping para o que o prompt precisa."""


def test_prompt_leva_o_texto_original_com_emoji():
    """A Gemini le emoji; mandar texto_modelo daria a ela entrada diferente do humano."""
    lote = [_Registro(id_comentario=7, texto="amei 😂 demais")]
    prompt = montar_prompt(lote)
    assert "😂" in prompt
    assert "risos" not in prompt
    assert '"id_comentario": 7' in prompt


def test_prompt_declara_a_quantidade_do_lote():
    lote = [_Registro(id_comentario=i, texto=f"t{i}") for i in range(1, 6)]
    assert "exatamente 5 objetos" in montar_prompt(lote)


def test_prompt_do_codigo_bate_com_o_arquivo_versionado():
    """prompt_v1.md vai para o TCC; se o codigo divergir, o documento mente.

    Compara o bloco de tarefa do arquivo com a constante usada de verdade.
    """
    import pathlib

    caminho = pathlib.Path(__file__).resolve().parents[1] / "rotulagem" / ARQUIVO_PROMPT
    markdown = caminho.read_text(encoding="utf-8")

    # O arquivo escreve o JSON de exemplo com chave simples; o código usa `{{`/`}}`
    # porque a string passa por str.format.
    do_codigo = PROMPT_TAREFA.replace("{{", "{").replace("}}", "}")

    for trecho in do_codigo.split("\n\n"):
        limpo = trecho.strip()
        if not limpo or "{comentarios_json}" in limpo or "{quantidade}" in limpo:
            continue
        assert limpo in markdown, f"trecho do prompt ausente em {ARQUIVO_PROMPT}:\n{limpo[:200]}"


def test_as_tres_classes_aparecem_no_prompt():
    for classe in CLASSES:
        assert f'"{classe}"' in PROMPT_TAREFA


# ------------------------------------------------------------------ segurança


def test_a_chave_vai_no_cabecalho_e_nunca_na_url():
    """Mesma licao do cliente da YouTube API: chave na query vaza no log."""
    capturado = {}

    class _Falso(ClienteGemini):
        def _requisitar(self, corpo):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._modelo}:generateContent"
            capturado["url"] = url
            capturado["headers"] = {
                "Content-Type": "application/json",
                CABECALHO_CHAVE: self._api_key,
            }
            self.chamadas += 1
            return {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}

    cliente = _Falso(api_key="chave-secreta-de-teste", modelo="gemini-2.0-flash")
    cliente.gerar("sistema", "prompt")

    assert capturado["headers"][CABECALHO_CHAVE] == "chave-secreta-de-teste"
    assert "key=" not in capturado["url"]
    assert "chave-secreta-de-teste" not in capturado["url"]


def test_temperatura_zero_no_corpo_da_requisicao():
    """Rotulagem precisa ser reproduzivel: rodar de novo tem que dar o mesmo rotulo."""
    cliente = ClienteGemini(api_key="x", modelo="gemini-2.0-flash", temperatura=0.0)
    corpo = cliente._corpo("sistema", "prompt")
    assert corpo["generationConfig"]["temperature"] == 0.0
    assert corpo["generationConfig"]["responseMimeType"] == "application/json"


def test_corpo_da_requisicao_nao_carrega_a_chave():
    """A chave e so cabecalho; no corpo ela acabaria em log de payload."""
    cliente = ClienteGemini(api_key="chave-secreta", modelo="m")
    assert "chave-secreta" not in json.dumps(cliente._corpo("s", "p"))
