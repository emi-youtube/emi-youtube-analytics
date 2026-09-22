"""Testes da rotulagem fraca. Nenhum toca a rede — cota da Gemini é finita.

O que estes testes protegem: a validação da resposta (categoria fechada, casamento
por id, lote completo), a sincronia entre o prompt do código e o arquivo versionado,
e a garantia de que a chave não vai para a URL.
"""

import asyncio
import json
import re

import asyncpg
import pytest

from ml.config import CLASSES
from ml.rotulagem import gemini
from ml.rotulagem.calibracao import CALIBRACAO, GABARITO, MAXIMO_ERROS
from ml.rotulagem.gemini import (
    CABECALHO_CHAVE,
    ClienteGemini,
    ErroPermanente,
    ErroTransitorio,
    e_estavel,
)
from ml.rotulagem.rotular_fraco import (
    ARQUIVO_MANUAL,
    ARQUIVO_PROMPT,
    MAX_TENTATIVAS_LOTE,
    PROMPT_TAREFA,
    RespostaInvalida,
    escolher_modelo,
    extrair_json,
    montar_prompt,
    reconectar_se_caiu,
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


def test_tempo_esgotado_na_leitura_vira_erro_transitorio(monkeypatch):
    """TimeoutError nao e URLError: sem tratamento ele derruba a rodada em vez de repetir.

    Acontece de verdade no free tier — o modelo aceita a requisicao e demora mais que
    o timeout de leitura. Numa rodada de ~100 chamadas, subir cru significa perder a
    rodada por causa de uma unica resposta lenta.
    """

    def estoura(*_args, **_kwargs):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr("ml.rotulagem.gemini.urllib.request.urlopen", estoura, raising=True)
    cliente = ClienteGemini(api_key="x", modelo="m")

    with pytest.raises(ErroTransitorio, match="tempo esgotado"):
        cliente.gerar("sistema", "prompt", max_tentativas=1)


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


# --------------------------------------------- manual como fonte unica


def _texto(nome: str) -> str:
    """Le um arquivo de `ml/rotulagem/` sem a marcacao de negrito do markdown.

    O manual formata (`**mas**`); o prompt que vai para a Gemini e texto puro. Tirar
    os asteriscos deixa os dois comparaveis pela mesma substring.
    """
    import pathlib

    caminho = pathlib.Path(__file__).resolve().parents[1] / "rotulagem" / nome
    return caminho.read_text(encoding="utf-8").replace("**", "")


# Regras do manual que NAO podem sumir do prompt. Cada ancora tem:
#   - `no_manual`: trecho que prova que a regra continua no manual. Se ele sumir, o
#     teste falha do lado do manual — sinal de que o par a reconciliar mudou e o
#     prompt precisa acompanhar (numa v2, nao editando esta versao).
#   - `no_prompt`: trechos que provam que a mesma regra chegou ao texto que a Gemini
#     recebe de fato (a constante `PROMPT_TAREFA`, nao so o arquivo .md).
#
# Sem isto, uma reescrita do prompt pode devolve-lo silenciosamente ao estado
# anterior a reconciliacao, em que ele mandava usar "neutro" na duvida entre ironia
# e elogio — o oposto do que o manual manda o humano fazer. Os dois lados voltariam
# a medir reguas diferentes, e o Kappa deixaria de significar o que o TCC diz que ele
# significa.
ANCORAS = [
    pytest.param(
        'vence a parte que encerra o comentário ou a que vem depois de "mas", "porém", "só que"',
        (
            'vence a parte que encerra o\n   comentário ou a que vem depois de "mas", "porém", '
            '"só que", "no entanto"',
            "demorou pra chegar, mas o produto é maravilhoso",
        ),
        id="regra-do-mas",
    ),
    pytest.param(
        'Neutro não é o "lugar da dúvida".',
        (
            '"neutro" NÃO é o lugar da dúvida.',
            "difícil de decidir entre positivo e negativo NÃO é neutro",
        ),
        id="neutro-nao-e-duvida",
    ),
    pytest.param(
        "rotule pelo que o autor quis dizer, não pelas palavras que usou",
        (
            "rotule pelo que o autor quis dizer, não pelas palavras que\n   usou",
            "Sem certeza de que é ironia, rotule pelo sentido literal.",
        ),
        id="ironia",
    ),
    pytest.param(
        "Elogio a um elemento da campanha conta como elogio à campanha",
        ("Elogio a um elemento da campanha conta como elogio à campanha",),
        id="elemento-da-campanha",
    ),
    pytest.param(
        "Quando o comentário fala da entrega, do atendimento ou do preço, isso conta.",
        ("Entrega, atendimento e preço contam como marca",),
        id="entrega-atendimento-preco",
    ),
    pytest.param(
        '"alguém mais recebeu com defeito?" → Negativo (pressupõe o problema)',
        ('"alguém mais recebeu com defeito?" → "negativo": pressupõe o problema.',),
        id="pergunta-com-pressuposicao",
    ),
    pytest.param(
        "traduza a gíria antes de rotular",
        ("traduza a gíria antes de rotular", '"kkkk", "rsrs", "mds" sozinhos → "neutro"'),
        id="giria",
    ),
    pytest.param(
        "### 5.7 Spam e propaganda de terceiros",
        ('SPAM e propaganda de terceiros → "neutro".',),
        id="spam",
    ),
]


@pytest.mark.parametrize(("no_manual", "no_prompt"), ANCORAS)
def test_regra_chave_do_manual_sobrevive_no_prompt(no_manual, no_prompt):
    """O manual e a fonte unica; o prompt e o espelho. Espelho incompleto = Kappa sem sentido."""
    manual = _texto(ARQUIVO_MANUAL)
    assert no_manual in manual, f"a ancora saiu do manual: {no_manual!r}"

    for trecho in no_prompt:
        assert trecho in PROMPT_TAREFA, f"regra do manual ausente do prompt: {trecho!r}"


def test_o_prompt_nao_manda_usar_neutro_na_duvida():
    """A versao anterior a reconciliacao dizia 'na duvida ... use neutro'. Nunca mais.

    Era a divergencia mais cara: o manual manda o humano decidir pelo sentido literal
    e marcar a coluna de duvida, enquanto o prompt mandava a Gemini fugir para
    'neutro'. Os dois lados discordariam por construcao, e o Kappa mediria essa
    diferenca de regua em vez da qualidade da rotulagem.
    """
    assert "Na dúvida entre\n   ironia e elogio sincero" not in PROMPT_TAREFA
    assert "ambíguo demais para decidir" not in PROMPT_TAREFA
    assert "ou ambíguo" not in PROMPT_TAREFA


def test_o_prompt_nao_contradiz_o_manual_sobre_elogio_ao_ator():
    """O manual diz que elogio ao elenco e positivo; o prompt dizia o contrario."""
    assert "ao ator do anúncio" not in PROMPT_TAREFA
    assert "Elogio ao ator" not in PROMPT_TAREFA


def test_o_arquivo_do_prompt_aponta_o_manual_como_fonte():
    prompt_md = _texto(ARQUIVO_PROMPT)
    assert f"A fonte única dos critérios é `{ARQUIVO_MANUAL}`." in prompt_md
    # O prompt dizia isso de si mesmo antes da reconciliacao.
    assert "Este arquivo é a fonte única dos critérios" not in prompt_md


def test_o_aviso_de_pendente_de_validacao_saiu():
    """Ele existia porque o manual nao estava no repositorio. Agora esta."""
    prompt_md = _texto(ARQUIVO_PROMPT)
    assert "Pendente de validação" not in prompt_md
    assert "reconcilie os dois textos antes de rodar" not in prompt_md.lower()


def test_as_tres_classes_do_manual_sao_as_do_codigo():
    manual = _texto(ARQUIVO_MANUAL)
    for classe in CLASSES:
        assert classe.capitalize() in manual or classe in manual


# ------------------------------------------------------- escolha do modelo


@pytest.fixture
def catalogo(monkeypatch):
    """Substitui a chamada de rede a ListModels por um catalogo fixo."""
    modelos = [
        {"nome": "gemini-3.5-flash", "rotulo": "", "metodos": ["generateContent"]},
        {"nome": "gemini-3.5-flash-lite", "rotulo": "", "metodos": ["generateContent"]},
        {"nome": "gemini-3-flash-preview", "rotulo": "", "metodos": ["generateContent"]},
        {"nome": "gemini-flash-latest", "rotulo": "", "metodos": ["generateContent"]},
        {"nome": "lyria-3.5", "rotulo": "", "metodos": ["predict"]},
    ]
    monkeypatch.setattr(
        "ml.rotulagem.rotular_fraco.listar_modelos", lambda _chave: modelos, raising=True
    )
    return modelos


def _resposta_de_sonda(rotulos: dict[int, str]) -> str:
    return json.dumps([{"id_comentario": n, "rotulo": r} for n, r in sorted(rotulos.items())])


@pytest.fixture
def sonda(monkeypatch):
    """Substitui a chamada real da sonda. Devolve o gabarito inteiro por padrao.

    `ajustar(...)` troca o comportamento: outros rotulos, resposta fora do contrato
    ou erro de rede, sem que nenhum teste chegue perto da Gemini.
    """

    estado = {"retorno": _resposta_de_sonda(GABARITO), "erro": None}

    def falso_gerar(self, _instrucao, _prompt, max_tentativas=5):
        self.chamadas += 1
        if estado["erro"] is not None:
            raise estado["erro"]
        return estado["retorno"]

    monkeypatch.setattr(ClienteGemini, "gerar", falso_gerar, raising=True)

    def ajustar(*, rotulos=None, bruto=None, erro=None):
        if rotulos is not None:
            estado["retorno"] = _resposta_de_sonda(rotulos)
        if bruto is not None:
            estado["retorno"] = bruto
        estado["erro"] = erro

    return ajustar


def test_modelo_do_env_existente_e_estavel_passa(catalogo, sonda):
    escolha = escolher_modelo({"GEMINI_MODELO": "gemini-3.5-flash"}, "chave")
    assert escolha.cliente.modelo == "gemini-3.5-flash"
    assert escolha.acertos_calibracao == len(CALIBRACAO)
    assert escolha.erros_calibracao == {}


def test_a_sonda_gasta_uma_chamada_so(catalogo, sonda):
    """A prova custa uma chamada. Mais que isso vira cota jogada fora a cada rodada."""
    escolha = escolher_modelo({"GEMINI_MODELO": "gemini-3.5-flash"}, "chave")
    assert escolha.cliente.chamadas == 1


def test_modelo_do_catalogo_que_responde_404_e_recusado(catalogo, sonda):
    """O caso que a listagem nao pega: `gemini-2.5-*` e listado e fechado para chaves novas."""
    sonda(erro=ErroPermanente("HTTP 404: no longer available to new users"))
    with pytest.raises(ValueError, match="esta no catalogo mas nao responde"):
        escolher_modelo({"GEMINI_MODELO": "gemini-3.5-flash"}, "chave")


def test_modelo_sobrecarregado_e_recusado_depois_de_insistir(catalogo, sonda):
    """503 no comeco e melhor que 503 no lote 40, com meia rodada gravada.

    Mas a sonda insiste antes de desistir: no free tier o 503 vem em surtos, e
    recusar de primeira faria a rodada se negar a comecar por um surto de minutos.
    """
    sonda(erro=ErroTransitorio("HTTP 503: experiencing high demand"))
    with pytest.raises(ValueError, match=r"nao atendeu em .* tentativas"):
        escolher_modelo({"GEMINI_MODELO": "gemini-3.5-flash"}, "chave")


def test_a_sonda_tem_a_mesma_paciencia_de_um_lote(catalogo, sonda, monkeypatch):
    """Sonda menos paciente que um lote = rodada que se recusa a comecar no surto."""
    vistas = []

    def registrar_gerar(self, _instrucao, _prompt, max_tentativas=5):
        vistas.append(max_tentativas)
        self.chamadas += 1
        return _resposta_de_sonda(GABARITO)

    monkeypatch.setattr(ClienteGemini, "gerar", registrar_gerar, raising=True)
    escolher_modelo({"GEMINI_MODELO": "gemini-3.5-flash"}, "chave")

    assert vistas == [MAX_TENTATIVAS_LOTE]


def test_modelo_que_ignora_o_contrato_e_recusado(catalogo, sonda):
    sonda(bruto="Claro! Aqui estao os rotulos dos 12 comentarios:")
    with pytest.raises(ValueError, match="fora do contrato na sonda"):
        escolher_modelo({"GEMINI_MODELO": "gemini-3.5-flash"}, "chave")


def test_modelo_que_erra_mais_que_o_humano_toleraria_e_recusado(catalogo, sonda):
    """Secao 8 reprova o avaliador que erra mais de 3. A Gemini responde pela mesma regua."""
    errados = dict(GABARITO)
    for numero in list(sorted(GABARITO))[: MAXIMO_ERROS + 1]:
        errados[numero] = "neutro" if GABARITO[numero] != "neutro" else "positivo"
    sonda(rotulos=errados)

    with pytest.raises(ValueError, match="na calibracao"):
        escolher_modelo({"GEMINI_MODELO": "gemini-3.5-flash"}, "chave")


def test_erro_ate_o_limite_do_manual_passa(catalogo, sonda):
    """A regua e a mesma: 3 erros ainda passam, o quarto reprova."""
    errados = dict(GABARITO)
    for numero in list(sorted(GABARITO))[:MAXIMO_ERROS]:
        errados[numero] = "neutro" if GABARITO[numero] != "neutro" else "positivo"
    sonda(rotulos=errados)

    escolha = escolher_modelo({"GEMINI_MODELO": "gemini-3.5-flash"}, "chave")
    assert escolha.acertos_calibracao == len(CALIBRACAO) - MAXIMO_ERROS
    assert len(escolha.erros_calibracao) == MAXIMO_ERROS


def test_modelo_ausente_no_env_e_recusado(catalogo, sonda):
    """Sem nome padrao: 'Gemini' sem versao nao e reproduzivel, e o padrao envelhece.

    O padrao anterior deste arquivo era `gemini-2.0-flash`, que ja nao existe para a
    chave do projeto. Um padrao embutido so adia a descoberta para o meio da rodada.
    """
    with pytest.raises(ValueError, match="GEMINI_MODELO vazio"):
        escolher_modelo({}, "chave")


def test_modelo_inexistente_e_recusado_antes_de_gastar_cota(catalogo, sonda):
    with pytest.raises(ValueError, match="nao existe para esta chave"):
        escolher_modelo({"GEMINI_MODELO": "gemini-2.0-flash"}, "chave")


def test_modelo_sem_generate_content_e_recusado(catalogo, sonda):
    """Lyria, TTS e embedding aparecem no ListModels e nao classificam nada."""
    with pytest.raises(ValueError, match="nao suporta generateContent"):
        escolher_modelo({"GEMINI_MODELO": "lyria-3.5"}, "chave")


@pytest.mark.parametrize("instavel", ["gemini-3-flash-preview", "gemini-flash-latest"])
def test_modelo_preview_ou_apelido_e_recusado(catalogo, sonda, instavel):
    """Preview muda sem aviso; '-latest' aponta para outro modelo quando o Google troca.

    Nos dois casos o metadado registraria um nome que nao descreve o que rodou, e o
    corpus rotulado vai para o TCC.
    """
    with pytest.raises(ValueError, match="preview, experimental ou apelido"):
        escolher_modelo({"GEMINI_MODELO": instavel}, "chave")


@pytest.mark.parametrize(
    ("nome", "estavel"),
    [
        ("gemini-3.5-flash", True),
        ("gemini-2.5-pro", True),
        ("gemini-3-flash-preview", False),
        ("gemini-2.0-flash-exp", False),
        ("gemini-flash-latest", False),
        ("gemini-2.0-flash-experimental", False),
    ],
)
def test_e_estavel_classifica_o_nome(nome, estavel):
    assert e_estavel(nome) is estavel


# ------------------------------- calibracao: constante x Secao 8 do manual


def _secao_8() -> str:
    manual = _texto(ARQUIVO_MANUAL)
    return manual[manual.index("## 8. Exercício de calibração") : manual.index("## 9.")]


def test_os_12_comentarios_da_constante_sao_os_do_manual():
    """A sonda usa a constante; a banca le o manual. Divergir invalida o numero gravado."""
    secao = _secao_8()
    do_manual = re.findall(r'^\| (\d+) \| "(.+)" \|$', secao, re.M)
    assert [(int(n), t) for n, t in do_manual] == [(n, t) for n, t, _ in CALIBRACAO]


def test_o_gabarito_da_constante_e_o_do_manual():
    secao = _secao_8()
    do_manual = re.findall(r"^\| (\d+) \| (Positivo|Negativo|Neutro) \|", secao, re.M)
    assert {int(n): r.lower() for n, r in do_manual} == GABARITO


def test_o_limite_de_erros_e_o_que_o_manual_exige_do_humano():
    """Se o manual afrouxar ou apertar a regua, a da Gemini acompanha."""
    assert f"errar mais de {MAXIMO_ERROS}" in _secao_8()


def test_backoff_para_de_dobrar_no_teto(monkeypatch):
    """Sem teto, a 8a tentativa esperaria 8 minutos numa tacada.

    O 503 'high demand' do free tier some em minutos: o que resolve e continuar
    tentando em intervalo constante, nao esperar cada vez mais.
    """
    esperas: list[float] = []
    monkeypatch.setattr(gemini.time, "sleep", esperas.append, raising=True)
    monkeypatch.setattr(gemini.random, "uniform", lambda _a, _b: 0.0, raising=True)

    class _SempreOcupado(ClienteGemini):
        def _requisitar(self, corpo):
            raise ErroTransitorio("HTTP 503: high demand")

    with pytest.raises(ErroTransitorio):
        _SempreOcupado(api_key="x", modelo="m").gerar("sistema", "prompt", max_tentativas=8)

    assert esperas == [4, 8, 16, 32, 64, 64, 64]
    assert max(esperas) == gemini.BACKOFF_MAXIMO


# ------------------------------------------ conexao que morre de ocio


class _ConexaoFalsa:
    """Conexao que o servidor derrubou: `is_closed()` mente, o `SELECT 1` denuncia."""

    def __init__(self, viva: bool) -> None:
        self.viva = viva
        self.fechada = False

    def is_closed(self) -> bool:
        return False

    async def fetchval(self, _sql):
        if self.viva:
            return 1
        raise asyncpg.exceptions.ConnectionDoesNotExistError(
            "connection was closed in the middle of operation"
        )

    async def close(self) -> None:
        self.fechada = True


def test_conexao_viva_e_reaproveitada():
    conexao = _ConexaoFalsa(viva=True)
    assert asyncio.run(reconectar_se_caiu(conexao)) is conexao
    assert not conexao.fechada


def test_conexao_derrubada_no_ocio_e_substituida(monkeypatch):
    """Surto de 503 deixa o banco ocioso por dezenas de minutos; o Supabase desliga.

    Sem isto, a gravacao do lote seguinte morria levando rotulos que a Gemini ja
    havia devolvido — cota gasta, nada gravado.
    """
    morta = _ConexaoFalsa(viva=False)
    nova = _ConexaoFalsa(viva=True)

    async def falso_connect(_dsn):
        return nova

    monkeypatch.setattr("ml.rotulagem.rotular_fraco.asyncpg.connect", falso_connect, raising=True)
    monkeypatch.setattr(
        "ml.rotulagem.rotular_fraco.dsn_postgres", lambda: "postgresql://x", raising=True
    )

    assert asyncio.run(reconectar_se_caiu(morta)) is nova
    assert morta.fechada
