"""Configuração compartilhada pelos scripts do pipeline de IA.

O `ml/` NÃO importa nada de `backend/` (CLAUDE.md Seção 3): a comunicação entre as
duas metades é por artefato (arquivo de modelo + `model_card.json`) e pelo banco.
Por isso esta camada lê o `.env` por conta própria, em vez de reaproveitar o
`app.core.config` do backend.

A chave da Gemini mora no `.env` do PRÓPRIO ml/ (`ml/.env`), nunca no `.env` da
raiz que o backend carrega (CLAUDE.md regra 3: a Gemini não roda em produção, e o
backend de produção não pode ter chave de LLM nem por acidente).
"""

from pathlib import Path

# ml/config.py -> sobe 1 nível até a raiz do repositório
RAIZ_REPO = Path(__file__).resolve().parents[1]

DIRETORIO_ML = Path(__file__).resolve().parent
DIRETORIO_DADOS = DIRETORIO_ML / "dados"
DIRETORIO_CURADORIA = DIRETORIO_ML / "curadoria"

# Semente única do pipeline. Toda amostragem aleatória do ml/ parte daqui — trocar
# este valor muda o corpus, então ele é um parâmetro do experimento, não um detalhe.
SEMENTE = 42

# Identificador do tokenizer/modelo base (CLAUDE.md Seção 2).
MODELO_BASE = "neuralmind/bert-base-portuguese-cased"

# Comprimento máximo de sequência que o fine-tuning vai usar. A medição em
# `ml/medicao/` existe justamente para checar se este valor cobre o corpus.
MAX_LENGTH = 128

# Rótulos válidos, na ordem em que aparecem no documento acadêmico. Categoria
# fechada: qualquer coisa fora disto é erro, não um rótulo novo.
CLASSES = ("positivo", "negativo", "neutro")


def carregar_env() -> dict[str, str]:
    """Lê o `.env` da raiz em um dicionário, sem dependência externa.

    Formato simples `CHAVE=valor`, que é o que o arquivo do projeto usa; linhas
    em branco e comentários são ignorados.
    """
    caminho = RAIZ_REPO / ".env"
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} não encontrado. Copie env.example para .env e preencha os valores."
        )

    valores: dict[str, str] = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        chave, valor = limpa.split("=", 1)
        valores[chave.strip()] = valor.strip()
    return valores


def dsn_postgres() -> str:
    """DSN no formato que o asyncpg entende.

    O backend usa `postgresql+asyncpg://` porque quem consome é o SQLAlchemy; o
    asyncpg puro não aceita o sufixo do dialeto, então ele sai daqui.
    """
    env = carregar_env()
    url = env.get("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL vazio no .env")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def carregar_env_ml() -> dict[str, str]:
    """Lê `ml/.env` — o ambiente de TREINO, separado do `.env` de produção.

    Arquivo separado de propósito (CLAUDE.md regra 3). Se a chave da Gemini
    estivesse no `.env` da raiz, ela seria carregada pelo `app.core.config` do
    backend e acabaria no ambiente de produção junto com o resto.
    """
    caminho = DIRETORIO_ML / ".env"
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} não encontrado. Copie ml/env.example para ml/.env e preencha "
            "a GEMINI_API_KEY. Ela NÃO vai no .env da raiz (CLAUDE.md regra 3)."
        )

    valores: dict[str, str] = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        chave, valor = limpa.split("=", 1)
        valores[chave.strip()] = valor.strip()
    return valores


def chave_gemini() -> str:
    """Chave da Gemini, só para os scripts offline de rotulagem fraca."""
    chave = carregar_env_ml().get("GEMINI_API_KEY", "")
    if not chave:
        raise ValueError("GEMINI_API_KEY vazia em ml/.env")
    return chave
