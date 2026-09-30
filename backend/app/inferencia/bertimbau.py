"""Segunda implementação do `Classificador`: o BERTimbau fine-tuned do projeto.

Entra pela costura que `base.py` desenhou para isso: o worker de inferência não muda
uma linha. Ele continua aplicando `preparar_texto`, pedindo um rótulo e gravando; o
que muda é quem responde.

O que esta camada faz, na ordem em que o worker sobe:

1. **confere a integridade** dos arquivos da pasta contra o manifesto versionado
   (`bertimbau_manifesto.json`), arquivo por arquivo, por `sha256`. Os pesos (~420 MB)
   ficam fora do git, como o SentiLex; um download truncado ou um modelo trocado não
   pode virar classificação diferente em silêncio;
2. **lê o `model_card.json`**: `id2label`, `max_length` e `versao_preprocessamento`
   saem daqui, nunca do código (CLAUDE.md regra 5). A versão do pré-processamento
   passa pelo portão de `Classificador.validar`, o mesmo do léxico;
3. **carrega tokenizer e pesos em float32** (PyTorch). O ONNX int8 foi reprovado no
   ensaio — perdeu 4 pontos de F1 macro contra um portão de 1 (ml/treino/README.md).

Qualquer falha nessas três etapas vira `ClassificadorIndisponivel`, e é o `runner` que
decide o que fazer com ela: hoje, cair para o léxico (`workers/runner.py`).

**A justificativa é a confiança do modelo**, não "palavras decisivas": o BERTimbau não
tem essa explicação, e inventar uma (atenção, gradiente) seria mostrar à PME algo que
parece causa e não é. O que ele tem é a distribuição da softmax sobre as três classes,
e é ela que vai para a coluna `justificativa` — `ANALISES_SENTIMENTO` não tem coluna
`confianca` (o contrato da API a declara, sempre nula; ver `schemas/resultado.py`). A
softmax não é probabilidade calibrada: é a certeza relativa do modelo, e o texto diz
"confiança do modelo", não "probabilidade".

`torch` e `transformers` são importados DENTRO de `de_pasta`, e não no topo do módulo:
a API importa `app.inferencia` sem nunca carregar o modelo, e um ambiente sem as duas
bibliotecas tem de chegar ao léxico com uma mensagem clara, não com `ImportError` no
import do runner.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from app.inferencia.base import (
    SENTIMENTOS_VALIDOS,
    Classificacao,
    Classificador,
    ClassificadorIndisponivel,
    DescritorVersao,
)

logger = logging.getLogger(__name__)

ARQUIVO_MANIFESTO = Path(__file__).with_name("bertimbau_manifesto.json")

ARQUIVO_CARTAO = "model_card.json"

COMO_OBTER = (
    "Os pesos nao sao versionados (~420 MB). Rode `python -m app.inferencia.baixar_bertimbau` "
    "(baixa do Hugging Face Hub e confere o sha256; ver docs/DEPLOY.md) ou aponte "
    "BERTIMBAU_PATH no .env para a pasta que ja tem os arquivos do manifesto."
)

# Lê um arquivo grande em blocos para o sha256: os pesos têm ~420 MB e não precisam
# estar inteiros na memória só para serem conferidos.
TAMANHO_DO_BLOCO = 1 << 20

# Recebe o texto pré-processado e devolve as probabilidades da softmax, na ordem dos
# índices do modelo (a mesma do `id2label`). É a fronteira que os testes substituem.
Preditor = Callable[[str], Sequence[float]]


def ler_manifesto(caminho: Path = ARQUIVO_MANIFESTO) -> dict[str, Any]:
    """O manifesto versionado: nome, versão e o sha256 de cada arquivo da pasta."""
    return json.loads(caminho.read_text(encoding="utf-8"))


def sha256_de(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(TAMANHO_DO_BLOCO), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def conferir_pasta(pasta: Path, manifesto: dict[str, Any]) -> None:
    """Todo arquivo do manifesto presente e com o sha256 esperado. Junta todos os erros.

    Ausente e diferente são mensagens diferentes, como no léxico: um é "baixe", o
    outro é "o que está aqui não é o modelo avaliado".
    """
    if not pasta.is_dir():
        raise ClassificadorIndisponivel(
            f"pasta do BERTimbau nao encontrada em {pasta}\n{COMO_OBTER}"
        )

    ausentes: list[str] = []
    divergentes: list[str] = []
    for nome, esperado in manifesto["arquivos"].items():
        arquivo = pasta / nome
        if not arquivo.is_file():
            ausentes.append(nome)
        elif sha256_de(arquivo) != esperado:
            divergentes.append(nome)

    if ausentes or divergentes:
        linhas = [f"pasta do BERTimbau em {pasta} nao confere com o manifesto:"]
        linhas += [f"  ausente:    {nome}" for nome in ausentes]
        linhas += [f"  sha256 diferente: {nome}" for nome in divergentes]
        linhas.append(
            "Classificar com outros pesos muda o rotulo em silencio e desalinha o numero "
            f"do Capitulo 5. {COMO_OBTER}"
        )
        raise ClassificadorIndisponivel("\n".join(linhas))


def ler_cartao(pasta: Path, manifesto: dict[str, Any]) -> dict[str, Any]:
    """O `model_card.json`, conferido contra o manifesto e contra as classes do banco."""
    cartao = json.loads((pasta / ARQUIVO_CARTAO).read_text(encoding="utf-8"))

    faltando = [
        campo
        for campo in ("nome_modelo", "versao", "id2label", "max_length", "versao_preprocessamento")
        if campo not in cartao
    ]
    if faltando:
        raise ClassificadorIndisponivel(
            f"{pasta / ARQUIVO_CARTAO} sem campo(s): {', '.join(faltando)}"
        )

    identidade = (cartao["nome_modelo"], cartao["versao"])
    if identidade != (manifesto["nome_modelo"], manifesto["versao"]):
        raise ClassificadorIndisponivel(
            f"o cartao em {pasta} e de {identidade[0]} {identidade[1]}, mas o manifesto "
            f"espera {manifesto['nome_modelo']} {manifesto['versao']}"
        )

    # `id2label` tem chave string (JSON não tem chave inteira). A ordem por índice é a
    # ordem das saídas do modelo; um buraco ou um rótulo fora do CHECK do banco seria
    # `IntegrityError` no meio de um lote, então falha aqui.
    id2label = cartao["id2label"]
    if {int(chave) for chave in id2label} != set(range(len(id2label))):
        raise ClassificadorIndisponivel(f"id2label com buraco no cartao: {sorted(id2label)}")
    fora = set(id2label.values()) - SENTIMENTOS_VALIDOS
    if fora:
        raise ClassificadorIndisponivel(f"id2label com rotulo fora do banco: {sorted(fora)}")
    return cartao


def formatar_confianca(probabilidades: dict[str, float]) -> str:
    """`{"positivo": 0.94, ...}` -> `"confiança do modelo: positivo 94% · neutro 4% · ..."`.

    Da maior para a menor: o primeiro é o rótulo gravado, e o segundo é o que a PME
    precisa ver para saber se foi decisão folgada ou apertada.
    """
    ordenadas = sorted(probabilidades.items(), key=lambda item: item[1], reverse=True)
    partes = " · ".join(f"{classe} {round(100 * valor)}%" for classe, valor in ordenadas)
    return f"confiança do modelo: {partes}"


class ClassificadorBertimbau(Classificador):
    """BERTimbau carregado em memória, pronto para classificar um comentário por vez.

    Um por vez porque é assim que o worker chama (`classificar(texto)`): sem lote de
    tensor, sem padding. No escopo do projeto é suficiente — 1.000 comentários em
    ~104 s num núcleo (ml/medicao/relatorio_tempo_inferencia.json), contra a meta de
    3 minutos da Tabela 15 do TC2.
    """

    def __init__(
        self, preditor: Preditor, cartao: dict[str, Any], proveniencia: dict[str, Any]
    ) -> None:
        self._preditor = preditor
        self._cartao = cartao
        self._classes = tuple(
            cartao["id2label"][str(indice)] for indice in range(len(cartao["id2label"]))
        )
        self._proveniencia = proveniencia

    @classmethod
    def de_pasta(
        cls, pasta: Path, manifesto: dict[str, Any] | None = None
    ) -> "ClassificadorBertimbau":
        """Confere, lê o cartão e carrega os pesos. Falha AQUI, não durante uma execução."""
        manifesto = manifesto if manifesto is not None else ler_manifesto()
        conferir_pasta(pasta, manifesto)
        cartao = ler_cartao(pasta, manifesto)

        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as erro:
            raise ClassificadorIndisponivel(
                f"torch/transformers nao instalados neste ambiente ({erro}). "
                "Instale o backend/requirements.txt."
            ) from erro

        try:
            tokenizador = AutoTokenizer.from_pretrained(pasta)
            modelo = AutoModelForSequenceClassification.from_pretrained(
                pasta, torch_dtype=torch.float32
            )
        except Exception as erro:
            raise ClassificadorIndisponivel(
                f"falha ao carregar o BERTimbau de {pasta}: {erro!r}"
            ) from erro
        modelo.eval()

        if modelo.config.num_labels != len(cartao["id2label"]):
            raise ClassificadorIndisponivel(
                f"o modelo em {pasta} tem {modelo.config.num_labels} saidas, mas o cartao "
                f"declara {len(cartao['id2label'])} rotulos"
            )

        max_length = cartao["max_length"]

        def prever(texto_modelo: str) -> list[float]:
            entrada = tokenizador(
                texto_modelo, truncation=True, max_length=max_length, return_tensors="pt"
            )
            with torch.inference_mode():
                return modelo(**entrada).logits.softmax(dim=-1)[0].tolist()

        logger.info(
            "bertimbau carregado pasta=%s nome=%s versao=%s max_length=%s",
            pasta,
            cartao["nome_modelo"],
            cartao["versao"],
            max_length,
        )
        return cls(prever, cartao, _proveniencia(cartao, manifesto))

    @property
    def descritor(self) -> DescritorVersao:
        return DescritorVersao(
            nome_modelo=self._cartao["nome_modelo"],
            versao=self._cartao["versao"],
            proveniencia=self._proveniencia,
        )

    @property
    def versao_preprocessamento(self) -> str:
        # Do cartão, não do pacote instalado: é a versão com que o modelo foi TREINADO.
        # O portão em `validar` compara as duas e recusa se divergirem (regra 5).
        return self._cartao["versao_preprocessamento"]

    def classificar(self, texto_modelo: str) -> Classificacao:
        probabilidades = list(self._preditor(texto_modelo))
        if len(probabilidades) != len(self._classes):
            raise ValueError(
                f"o modelo devolveu {len(probabilidades)} saidas para {len(self._classes)} classes"
            )
        por_classe = dict(zip(self._classes, probabilidades, strict=True))
        sentimento = max(por_classe, key=por_classe.__getitem__)
        return Classificacao(sentimento=sentimento, justificativa=formatar_confianca(por_classe))


def _proveniencia(cartao: dict[str, Any], manifesto: dict[str, Any]) -> dict[str, Any]:
    """O que vai para VERSOES_MODELO.metricas_avaliacao: prova de qual artefato rotulou.

    Os sha256 do manifesto identificam os pesos; o resto é o cartão, sem as métricas
    de validação (rótulo fraco — não são número de capítulo, e não devem ser lidas
    como tal no banco). A avaliação contra o gabarito humano entra inteira.
    """
    return {
        "metodo": "BERTimbau fine-tuned, pytorch float32",
        "modelo_base": cartao.get("modelo_base"),
        "semente": cartao.get("semente"),
        "treinado_em_utc": cartao.get("treinado_em_utc"),
        "fonte_de_treino": cartao.get("dados", {}).get("fonte"),
        "id2label": cartao["id2label"],
        "max_length": cartao["max_length"],
        "versao_preprocessamento": cartao["versao_preprocessamento"],
        "avaliacao_gabarito_humano": cartao.get("avaliacao_gabarito_humano"),
        "sha256_arquivos": manifesto["arquivos"],
        "papel": "classificador de producao; o lexico (SentiLex) e a contingencia",
    }
