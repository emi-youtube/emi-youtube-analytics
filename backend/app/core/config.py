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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
