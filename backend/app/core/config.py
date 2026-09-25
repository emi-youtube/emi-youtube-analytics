"""Configuração da aplicação, carregada do .env na raiz do repositório."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> sobe 3 níveis até a raiz do repositório
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    youtube_api_key: str

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:4200"

    # Arquivo do SentiLex-PT02 que o classificador léxico carrega (worker de
    # inferência). Fora do git — dado de terceiro, 6,9 MB — então é configuração, não
    # constante. Vazio cai no padrão (ver `caminho_sentilex`), e não em `Path("")`:
    # quem copia o env.example e deixa a linha em branco tem que obter o padrão, não
    # um erro apontando para o diretório atual.
    sentilex_path: str = ""

    worker_poll_interval_seconds: int = 5
    # Tentativas de RETENTATIVA por job em erro transitório: as esperas são
    # 2, 4, 8 e 16s (+ jitter), então 4 corresponde a ~30s de insistência.
    worker_max_retries: int = 4
    # Teto por execução, alinhado ao escopo do projeto (500 a 5.000 comentários).
    # Também segura a cota da YouTube API quando um vídeo tem centenas de páginas.
    worker_max_comentarios_por_execucao: int = 5000
    youtube_timeout_seconds: int = 30

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def caminho_sentilex(self) -> Path:
        """Onde procurar o arquivo do SentiLex, com o padrão do repositório.

        O padrão aponta para onde o experimento do `ml/` já baixa o recurso, para que
        quem rodou a linha de base do Capítulo 5 não precise de uma segunda cópia. Num
        deploy em que a pasta `ml/` não existe, `SENTILEX_PATH` é obrigatório — e a
        ausência aparece como falha de inicialização do worker, com o caminho que ele
        tentou (app/inferencia/lexico.py).
        """
        if self.sentilex_path.strip():
            return Path(self.sentilex_path.strip())
        return REPO_ROOT / "ml" / "lexico" / "dados" / "SentiLex-flex-PT02.txt"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
