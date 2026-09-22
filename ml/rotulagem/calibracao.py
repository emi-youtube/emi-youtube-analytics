"""Exercício de calibração da Seção 8 do manual, aplicado à Gemini.

Os mesmos 12 comentários que os avaliadores humanos rotulam antes da amostra
oficial. Aqui eles têm duas funções:

1. **Sonda antes da rodada.** Uma chamada real confirma o que o `ListModels` não
   confirma — que o modelo do `ml/.env` responde para esta chave, que o modo JSON
   funciona e que ele obedece à categoria fechada. Ver `escolher_modelo`.
2. **Número no metadado.** A rodada grava quantos dos 12 o modelo acertou, medido
   na própria sessão. "Escolhemos a Gemini X" é uma afirmação; "acertou 12/12 na
   mesma calibração que os avaliadores fizeram" é um dado que a banca pode conferir.

A régua é a mesma dos humanos de propósito (CLAUDE.md: a comparação entre Gemini e
humano só vale se os dois lerem o mesmo critério). O gabarito abaixo é cópia do manual, e
`ml/tests/test_rotulagem.py` falha se os dois divergirem.
"""

from ml.config import DIRETORIO_ML

ARQUIVO_MANUAL = "manual_rotulagem_v1.md"

# Seção 8 do manual, comentário e gabarito. Os pares 5/6 são as mesmas palavras em
# ordem inversa: é ali que a regra do "mas" aparece ou não aparece.
CALIBRACAO: tuple[tuple[int, str, str], ...] = (
    (1, "chorei com esse comercial, que lindo", "positivo"),
    (2, "mds que caro, nem fodendo que eu pago isso", "negativo"),
    (3, "alguém sabe se entrega em Manaus?", "neutro"),
    (4, "que atendimento EXCELENTE, esperei só 2 horas no chat 👏", "negativo"),
    (5, "produto bom mas a entrega atrasou uma semana", "negativo"),
    (6, "a entrega atrasou mas o produto é perfeito", "positivo"),
    (7, "😂😂😂", "neutro"),
    (8, "brabo demais esse anúncio", "positivo"),
    (9, "@mariana olha isso aqui", "neutro"),
    (10, "alguém mais recebeu com a tampa quebrada?", "negativo"),
    (11, "onde compro? preciso desse", "positivo"),
    (12, "ganhe dinheiro em casa, link na bio", "neutro"),
)

GABARITO: dict[int, str] = {numero: rotulo for numero, _, rotulo in CALIBRACAO}

# Mesma régua da Seção 8 para o avaliador humano: errar mais de 3 dos 12 reprova.
# Aplicar à Gemini um critério mais frouxo que o exigido dos colegas não se defende
# em banca — e um modelo que erra 4 dos 12 casos-escola vai errar o corpus inteiro.
MAXIMO_ERROS = 3


def lote_de_sonda() -> list[dict]:
    """Os 12 casos no formato que `montar_prompt` espera."""
    return [{"id_comentario": numero, "texto": texto} for numero, texto, _ in CALIBRACAO]


def avaliar(rotulos: dict[int, str]) -> tuple[int, dict[int, str]]:
    """Devolve `(acertos, {numero: rotulo_errado})` contra o gabarito do manual."""
    erros = {n: rotulos[n] for n in GABARITO if rotulos.get(n) != GABARITO[n]}
    return len(GABARITO) - len(erros), erros


def caminho_manual():
    return DIRETORIO_ML / "rotulagem" / ARQUIVO_MANUAL
