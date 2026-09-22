"""Mede o corpus com o tokenizer do BERTimbau. NÃO treina nem carrega pesos.

Responde duas perguntas que definem o `max_length` do fine-tuning:

1. qual a distribuição de comprimento em tokens, e quanto do corpus passa de 128;
2. quantos emoji o vocabulário do BERTimbau não conhece e vira `[UNK]`.

A segunda importa porque o corpus é de comentário de YouTube: se emoji viram `[UNK]`
em massa, o modelo perde justamente o sinal de sentimento mais direto que existe
nesse tipo de texto, e a decisão (normalizar? remover? traduzir para texto?) precisa
ser tomada com número na mão, antes do treino.

Comprimento é medido COM os tokens especiais ([CLS] e [SEP]), que é como o texto
chega ao modelo — é esse número que precisa caber no `max_length`.

Uso:
    python -m ml.medicao.medir_tokens
"""

import csv
import logging
import statistics
import sys
import unicodedata
from collections import Counter

from ml.config import DIRETORIO_DADOS, MAX_LENGTH, MODELO_BASE

logger = logging.getLogger("medir_tokens")

ARQUIVO_CORPUS = DIRETORIO_DADOS / "corpus.csv"

PERCENTIS = (50, 75, 90, 95, 99)
# Faixas do histograma, alinhadas às potências de 2 que se costuma usar em max_length.
FAIXAS = ((0, 16), (17, 32), (33, 64), (65, 128), (129, 256), (257, 512), (513, 10**9))

TOKEN_DESCONHECIDO = "[UNK]"


def e_emoji(caractere: str) -> bool:
    """Heurística por categoria/intervalo Unicode, sem dependência extra.

    `So` (Symbol, other) pega a maior parte dos emoji; os intervalos cobrem o que
    cai fora dele (emoticons, bandeiras, seletores de tom de pele, teclas).
    """
    if unicodedata.category(caractere) == "So":
        return True
    ponto = ord(caractere)
    return any(
        inicio <= ponto <= fim
        for inicio, fim in (
            (0x1F300, 0x1FAFF),  # pictogramas, emoticons, suplementos
            (0x1F1E6, 0x1F1FF),  # indicadores regionais (bandeiras)
            (0x2600, 0x27BF),  # símbolos diversos e dingbats
            (0xFE0F, 0xFE0F),  # seletor de variação (emoji vs. texto)
            (0x1F3FB, 0x1F3FF),  # modificadores de tom de pele
        )
    )


def carregar_textos() -> tuple[list[str], list[str], str]:
    """Devolve `(canônicos, do_modelo, versao_preprocessamento)`.

    O CSV traz as duas versões lado a lado: `texto` é o que humano e Gemini leem,
    `texto_modelo` é o que entra no BERTimbau. A medição que vale é a do segundo —
    o primeiro entra só para mostrar o tamanho do problema que a conversão resolve.
    """
    if not ARQUIVO_CORPUS.exists():
        raise SystemExit(
            f"{ARQUIVO_CORPUS} não existe. Rode antes: "
            "python -m ml.exportacao.exportar_corpus --id-execucao <N>"
        )
    with ARQUIVO_CORPUS.open(encoding="utf-8", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))

    faltando = {"texto", "texto_modelo", "versao_preprocessamento"} - set(linhas[0])
    if faltando:
        raise SystemExit(f"corpus.csv sem a(s) coluna(s) {sorted(faltando)} — reexporte o corpus.")

    return (
        [linha["texto"] for linha in linhas],
        [linha["texto_modelo"] for linha in linhas],
        linhas[0]["versao_preprocessamento"],
    )


def relatar_comprimento(comprimentos: list[int]) -> None:
    total = len(comprimentos)
    acima = sum(1 for n in comprimentos if n > MAX_LENGTH)

    logger.info("=" * 62)
    logger.info("DISTRIBUIÇÃO DE COMPRIMENTO (tokens, com [CLS]/[SEP])")
    logger.info("=" * 62)
    logger.info("  exemplos ........... %6d", total)
    logger.info("  mínimo ............. %6d", min(comprimentos))
    logger.info("  média .............. %6.1f", statistics.fmean(comprimentos))
    logger.info("  mediana ............ %6.1f", statistics.median(comprimentos))
    logger.info("  máximo ............. %6d", max(comprimentos))
    ordenados = sorted(comprimentos)
    for percentil in PERCENTIS:
        # Índice inteiro em vez de interpolação: o valor devolvido é um comprimento
        # que existe no corpus, e não uma média entre dois.
        indice = min(total - 1, (percentil * total) // 100)
        logger.info("  p%-2d ................ %6d", percentil, ordenados[indice])

    logger.info("-" * 62)
    logger.info("  histograma:")
    for inicio, fim in FAIXAS:
        quantos = sum(1 for n in comprimentos if inicio <= n <= fim)
        rotulo = f"{inicio}-{fim}" if fim < 10**9 else f">{inicio - 1}"
        barra = "#" * round(60 * quantos / total)
        logger.info("    %-9s %5d (%5.1f%%) %s", rotulo, quantos, 100 * quantos / total, barra)

    logger.info("-" * 62)
    logger.info(
        "  ACIMA DE %d TOKENS: %d de %d (%.2f%%) — seriam truncados",
        MAX_LENGTH,
        acima,
        total,
        100 * acima / total,
    )
    logger.info("=" * 62)


def relatar_unk(textos: list[str], tokenizer) -> None:
    """Contabiliza os `[UNK]` do corpus e quanto deles é culpa de emoji.

    Medido por diferença: tokeniza o corpus inteiro e de novo sem os emoji. O que
    some entre as duas contas é o `[UNK]` que veio de emoji.
    """
    id_unk = tokenizer.unk_token_id

    ids = tokenizer(textos, add_special_tokens=True, truncation=False)["input_ids"]
    total_unk = sum(sequencia.count(id_unk) for sequencia in ids)
    total_tokens = sum(len(sequencia) for sequencia in ids)
    com_unk = sum(1 for sequencia in ids if id_unk in sequencia)

    sem_emoji = ["".join(c for c in texto if not e_emoji(c)) for texto in textos]
    ids_sem_emoji = tokenizer(sem_emoji, add_special_tokens=True, truncation=False)["input_ids"]
    unk_restante = sum(sequencia.count(id_unk) for sequencia in ids_sem_emoji)
    unk_de_emoji = total_unk - unk_restante

    logger.info("")
    logger.info("=" * 62)
    logger.info("TOKENS [UNK] NO CORPUS")
    logger.info("=" * 62)
    logger.info(
        "  tokens [UNK] .................... %5d de %d (%.2f%%)",
        total_unk,
        total_tokens,
        100 * total_unk / total_tokens,
    )
    logger.info(
        "  exemplos com ao menos um [UNK] .. %5d de %d (%.1f%%)",
        com_unk,
        len(textos),
        100 * com_unk / len(textos),
    )
    if total_unk:
        logger.info(
            "  [UNK] vindos de emoji ........... %5d (%.1f%%)",
            unk_de_emoji,
            100 * unk_de_emoji / total_unk,
        )
        logger.info("  [UNK] de outros caracteres ...... %5d", unk_restante)
    logger.info("=" * 62)


def relatar_emoji(textos: list[str], tokenizer) -> None:
    """Conta emoji do corpus e quantos o tokenizer não representa."""
    ocorrencias: Counter[str] = Counter()
    for texto in textos:
        for caractere in texto:
            if e_emoji(caractere):
                ocorrencias[caractere] += 1

    # Um emoji pode virar [UNK] sozinho mas sobreviver dentro de uma sequência
    # (o ZWJ junta caracteres); medir isolado é o que responde "o vocabulário
    # conhece este símbolo?".
    desconhecidos: Counter[str] = Counter()
    conhecidos: Counter[str] = Counter()
    for caractere, quantos in ocorrencias.items():
        tokens = tokenizer.tokenize(caractere)
        if not tokens or all(token == TOKEN_DESCONHECIDO for token in tokens):
            desconhecidos[caractere] = quantos
        else:
            conhecidos[caractere] = quantos

    total_ocorrencias = sum(ocorrencias.values())
    total_unk = sum(desconhecidos.values())
    textos_com_emoji = sum(1 for t in textos if any(e_emoji(c) for c in t))

    logger.info("")
    logger.info("=" * 62)
    logger.info("EMOJI vs. VOCABULÁRIO DO BERTIMBAU")
    logger.info("=" * 62)
    logger.info(
        "  exemplos com ao menos um emoji ... %5d de %d (%.1f%%)",
        textos_com_emoji,
        len(textos),
        100 * textos_com_emoji / len(textos),
    )
    logger.info("  ocorrências de emoji ............. %5d", total_ocorrencias)
    logger.info("  emoji distintos .................. %5d", len(ocorrencias))
    if not total_ocorrencias:
        logger.info("  (corpus sem emoji)")
        logger.info("=" * 62)
        return
    logger.info(
        "  viram [UNK] ...................... %5d ocorrências (%.1f%%), %d distintos",
        total_unk,
        100 * total_unk / total_ocorrencias,
        len(desconhecidos),
    )
    # Emoji seguidos colapsam num [UNK] só ("Show 👏👍" -> ['Show', '[UNK]']), então
    # o modelo vê menos marcas do que o corpus tem ocorrências.
    logger.info("  (emoji consecutivos colapsam num único [UNK] — ver bloco acima)")
    logger.info(
        "  representados no vocabulário ..... %5d ocorrências (%.1f%%), %d distintos",
        sum(conhecidos.values()),
        100 * sum(conhecidos.values()) / total_ocorrencias,
        len(conhecidos),
    )

    if desconhecidos:
        logger.info("-" * 62)
        logger.info("  top 15 emoji perdidos como [UNK]:")
        for caractere, quantos in desconhecidos.most_common(15):
            nome = unicodedata.name(caractere, "SEM NOME")
            logger.info("    %-3s U+%-6X %5dx  %s", caractere, ord(caractere), quantos, nome)
    if conhecidos:
        logger.info("-" * 62)
        logger.info("  emoji que o vocabulário conhece:")
        for caractere, quantos in conhecidos.most_common(10):
            logger.info(
                "    %-3s U+%-6X %5dx  -> %s",
                caractere,
                ord(caractere),
                quantos,
                tokenizer.tokenize(caractere),
            )
    logger.info("=" * 62)


def relatar_ganho(canonicos: list[str], do_modelo: list[str], tokenizer) -> None:
    """Compara o canônico com o do modelo: é o que o pré-processamento comprou.

    O canônico é o texto como a pessoa escreveu — se ele fosse direto para o
    BERTimbau, os `[UNK]` desta primeira linha é que o modelo veria.
    """
    id_unk = tokenizer.unk_token_id

    def contar(textos: list[str]) -> tuple[int, int]:
        ids = tokenizer(textos, add_special_tokens=True, truncation=False)["input_ids"]
        return (
            sum(sequencia.count(id_unk) for sequencia in ids),
            sum(1 for sequencia in ids if id_unk in sequencia),
        )

    unk_antes, exemplos_antes = contar(canonicos)
    unk_depois, exemplos_depois = contar(do_modelo)

    logger.info("")
    logger.info("=" * 62)
    logger.info("GANHO DO PRE-PROCESSAMENTO (canonico -> texto_modelo)")
    logger.info("=" * 62)
    logger.info("  tokens [UNK] ......... %5d  ->  %5d", unk_antes, unk_depois)
    logger.info("  exemplos com [UNK] ... %5d  ->  %5d", exemplos_antes, exemplos_depois)
    if unk_antes:
        logger.info(
            "  reducao .............. %.1f%% dos [UNK] eliminados",
            100 * (unk_antes - unk_depois) / unk_antes,
        )
    logger.info("=" * 62)


def main() -> None:
    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    # Import tardio: deixa o erro de dependência aparecer depois da mensagem de
    # corpus ausente, que é o engano mais provável de quem roda isto pela 1ª vez.
    from transformers import AutoTokenizer

    canonicos, do_modelo, versao = carregar_textos()
    logger.info("corpus: %s exemplos de %s", len(do_modelo), ARQUIVO_CORPUS)
    logger.info("tokenizer: %s", MODELO_BASE)
    logger.info("pre-processamento do csv: versao %s", versao)
    logger.info("medindo a coluna `texto_modelo` (o que entra no BERTimbau)")

    tokenizer = AutoTokenizer.from_pretrained(MODELO_BASE)

    codificados = tokenizer(do_modelo, add_special_tokens=True, truncation=False)["input_ids"]
    relatar_comprimento([len(ids) for ids in codificados])
    relatar_unk(do_modelo, tokenizer)
    relatar_emoji(do_modelo, tokenizer)
    relatar_ganho(canonicos, do_modelo, tokenizer)


if __name__ == "__main__":
    main()
