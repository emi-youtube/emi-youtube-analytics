"""Modelo de frase: um `TipoFato` vira uma linha de português.

**Template, e não LLM.** A Gemini não roda em produção (CLAUDE.md regra 3) e o
backend não tem chave de LLM. Mas a razão aqui não é só a regra: a frase precisa
ser uma função determinística dos valores do fato. Uma frase gerada corre o risco
de afirmar mais do que os números sustentam — "a rejeição disparou" quando a
diferença foi de 3 pontos —, e é justamente contra esse tipo de afirmação que o
resto do pacote (amostra mínima, margem de incerteza) foi construído.

**As frases evitam causa.** "O tema X concentra as críticas" e não "os clientes
estão insatisfeitos com X": o motor mede comentário classificado, e por que o
comentário é negativo ele não sabe. A diferença parece sutil na tela e não é —
a segunda versão é uma conclusão de pesquisa, a primeira é a descrição de uma
contagem.

Número em português: vírgula decimal, uma casa. A conversão está aqui e não no
Angular porque o `valores` do fato e o `texto` têm que mostrar o mesmo número;
formatar nos dois lados é como eles divergem.
"""

from __future__ import annotations

from collections.abc import Callable

from app.insights.fatos import TipoFato, Valor

ASPA_ESQUERDA = "\u201c"
ASPA_DIREITA = "\u201d"


def numero(valor: float) -> str:
    """12.5 -> '12,5'. Uma casa, vírgula decimal, sem o ",0" inútil.

    >>> numero(12.5)
    '12,5'
    >>> numero(7.0)
    '7'
    """
    texto = f"{valor:.1f}".replace(".", ",")
    return texto.removesuffix(",0")


def _entre_aspas(valor: Valor) -> str:
    return f"{ASPA_ESQUERDA}{valor}{ASPA_DIREITA}"


def _tema_mais_criticado(valores: dict[str, Valor]) -> str:
    return (
        f"O tema {_entre_aspas(valores['rotulo_tema'])} é o que mais concentra críticas: "
        f"{numero(float(valores['percentual_negativo']))}% dos "
        f"{valores['comentarios_no_tema']} comentários ligados a ele são negativos, "
        f"contra {numero(float(valores['percentual_negativo_execucao']))}% na execução inteira."
    )


def _tema_melhor_recebido(valores: dict[str, Valor]) -> str:
    return (
        f"O tema {_entre_aspas(valores['rotulo_tema'])} é o mais bem recebido: "
        f"{numero(float(valores['percentual_positivo']))}% dos "
        f"{valores['comentarios_no_tema']} comentários ligados a ele são positivos, "
        f"contra {numero(float(valores['percentual_positivo_execucao']))}% na execução inteira."
    )


def _video_muito_negativo(valores: dict[str, Valor]) -> str:
    return (
        f"O vídeo {_entre_aspas(valores['titulo'])} recebe proporcionalmente muito mais "
        f"crítica que os demais: {numero(float(valores['percentual_negativo']))}% dos "
        f"{valores['comentarios_no_video']} comentários dele são negativos, "
        f"{numero(float(valores['multiplo_da_media']))}x a marca da execução "
        f"({numero(float(valores['percentual_negativo_execucao']))}%)."
    )


def _concentracao_das_criticas(valores: dict[str, Valor]) -> str:
    quantos = int(valores["temas_apontados"] or 0)
    sujeito = "temas concentram" if quantos > 1 else "tema concentra"
    return (
        f"As críticas estão concentradas: {quantos} {sujeito} "
        f"{numero(float(valores['percentual_das_criticas']))}% dos comentários negativos "
        f"da execução, de um total de {valores['temas_na_execucao']} temas "
        f"({valores['rotulos']})."
    )


def _variacao_de_sentimento(valores: dict[str, Valor]) -> str:
    diferenca = float(valores["diferenca_em_pontos"])
    verbo = "subiu" if diferenca > 0 else "caiu"
    return (
        f"A rejeição {verbo} entre as duas coletas: "
        f"{numero(float(valores['percentual_negativo_antes']))}% para "
        f"{numero(float(valores['percentual_negativo_depois']))}% de comentários negativos, "
        f"uma diferença de {numero(abs(diferenca))} pontos que excede a margem de "
        f"incerteza de {numero(float(valores['margem_em_pontos']))} pontos."
    )


def _evolucao_do_video(valores: dict[str, Valor]) -> str:
    diferenca = float(valores["diferenca_em_pontos"])
    verbo = "piorou" if diferenca > 0 else "melhorou"
    return (
        f"O vídeo {_entre_aspas(valores['titulo'])} {verbo} entre as coletas: "
        f"{numero(float(valores['percentual_negativo_antes']))}% para "
        f"{numero(float(valores['percentual_negativo_depois']))}% de comentários negativos, "
        f"uma diferença de {numero(abs(diferenca))} pontos acima da margem de "
        f"{numero(float(valores['margem_em_pontos']))} pontos."
    )


MODELOS: dict[TipoFato, Callable[[dict[str, Valor]], str]] = {
    TipoFato.TEMA_MAIS_CRITICADO: _tema_mais_criticado,
    TipoFato.TEMA_MELHOR_RECEBIDO: _tema_melhor_recebido,
    TipoFato.VIDEO_MUITO_NEGATIVO: _video_muito_negativo,
    TipoFato.CONCENTRACAO_DAS_CRITICAS: _concentracao_das_criticas,
    TipoFato.VARIACAO_DE_SENTIMENTO: _variacao_de_sentimento,
    TipoFato.EVOLUCAO_DO_VIDEO: _evolucao_do_video,
}
"""Um modelo por tipo de fato. Um `TipoFato` sem entrada aqui é erro de
programação, e `redigir` levanta — silenciar com uma frase genérica colocaria na
tela um texto que ninguém escreveu."""


def redigir(tipo: TipoFato, valores: dict[str, Valor]) -> str:
    """A frase daquele fato. Levanta `KeyError` se faltar modelo ou valor."""
    try:
        modelo = MODELOS[tipo]
    except KeyError:  # pragma: no cover - so acontece com TipoFato novo sem modelo
        raise KeyError(f"nenhum modelo de frase para {tipo}") from None
    return modelo(valores)
