"""Configuração compartilhada pelos scripts do pipeline de IA.

O `ml/` NÃO importa nada de `backend/` (CLAUDE.md Seção 3): a comunicação entre as
duas metades é por artefato (arquivo de modelo + `model_card.json`) e pelo banco.
Por isso esta camada lê o `.env` por conta própria, em vez de reaproveitar o
`app.core.config` do backend.

A chave da Gemini, quando entrar, mora aqui — nunca no `.env` de produção
(CLAUDE.md regra 3).
"""

from pathlib import Path

# ml/config.py -> sobe 1 nível até a raiz do repositório
RAIZ_REPO = Path(__file__).resolve().parents[1]

DIRETORIO_DADOS = Path(__file__).resolve().parent / "dados"

# Semente única do pipeline. Toda amostragem aleatória do ml/ parte daqui — trocar
# este valor muda o corpus, então ele é um parâmetro do experimento, não um detalhe.
SEMENTE = 42

# Identificador do tokenizer/modelo base (CLAUDE.md Seção 2).
MODELO_BASE = "neuralmind/bert-base-portuguese-cased"

# Comprimento máximo de sequência que o fine-tuning vai usar. A medição em
# `ml/medicao/` existe justamente para checar se este valor cobre o corpus.
MAX_LENGTH = 128


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
