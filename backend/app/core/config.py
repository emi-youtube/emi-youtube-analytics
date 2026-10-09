"""Configuração da aplicação, carregada do .env na raiz do repositório."""

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> sobe 3 níveis até a raiz do repositório
REPO_ROOT = Path(__file__).resolve().parents[3]

logger = logging.getLogger(__name__)

# Versão vigente dos Termos de Uso e da Política de Privacidade (ADR-012). Constante,
# não variável de ambiente: muda junto com o texto em
# `frontend/src/assets/legal/termos-v<versão>.md`, no mesmo PR. Ao mudar, todo usuário
# passa a ter aceite pendente e aceita de novo no próximo acesso.
VERSAO_TERMOS = "1.1"


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

    # Pasta com os pesos, o tokenizer e o model_card.json do BERTimbau (worker de
    # inferência). Fora do git (~420 MB): vazio cai no padrão (ver `caminho_bertimbau`).
    bertimbau_path: str = ""
    # De onde `app.inferencia.baixar_bertimbau` baixa a pasta: repositório PRIVADO do
    # Hugging Face Hub (docs/DEPLOY.md). A revisão pode ser um commit, para fixar; a
    # integridade não depende dela, e sim do sha256 do manifesto versionado.
    bertimbau_repo_hf: str = ""
    bertimbau_revisao_hf: str = "main"
    # Token de LEITURA do repositório privado. Só o download usa; nunca vai para log.
    hf_token: str = ""

    # --- Empresas (ADR-011) ---
    # Teto de membros por empresa, contando os convites pendentes. Projeto para PME:
    # o limite existe para um convite vazado não virar porta aberta.
    empresa_max_membros: int = 10
    # Teto de DONOS por empresa (ADR-013), contando convites de dono pendentes: dono
    # gerencia membros e apaga qualquer modelo, então "todo mundo é dono" é o mesmo
    # que não ter papel nenhum.
    empresa_max_donos: int = 3

    # --- E-mail transacional (convites e redefinição de senha) ---
    # "log": não envia; em desenvolvimento escreve a mensagem (com o link) no log do
    # servidor, e em produção só avisa que NÃO enviou — link de redefinição em log
    # de produção seria credencial exposta. "resend": envia pela API do Resend.
    email_provedor: str = "log"
    resend_api_key: str = ""
    # Remetente verificado no Resend. O domínio de testes dele só entrega para o
    # e-mail da própria conta: para convidar de verdade, verifique um domínio.
    email_remetente: str = "Emi Analytics <onboarding@resend.dev>"
    email_timeout_seconds: int = 10
    # Base dos links que vão no e-mail (convite e redefinição): a URL do frontend.
    frontend_url: str = "http://localhost:4200"

    worker_poll_interval_seconds: int = 5
    # Depois de quantos minutos em 'processando' um job é considerado abandonado
    # pelo worker e devolvido à fila (`workers/fila.devolver_presos`). Tem de ser
    # BEM maior que o job mais lento: devolver um job que só está demorando faria
    # dois workers processarem a mesma execução ao mesmo tempo. No escopo do
    # projeto (500 a 5.000 comentários) a etapa mais lenta leva segundos.
    worker_timeout_job_minutos: int = 15
    # De quanto em quanto tempo o runner roda o reaper. Não precisa ser frequente
    # — o que ele corrige já está parado há 15 minutos —, e varrer a cada ciclo
    # de polling (5s) seria consulta a mais sem ganho nenhum.
    worker_reaper_intervalo_segundos: int = 60
    # Tentativas de RETENTATIVA por job em erro transitório: as esperas são
    # 2, 4, 8 e 16s (+ jitter), então 4 corresponde a ~30s de insistência.
    worker_max_retries: int = 4
    # Teto por execução, alinhado ao escopo do projeto (500 a 5.000 comentários).
    # Também segura a cota da YouTube API quando um vídeo tem centenas de páginas.
    worker_max_comentarios_por_execucao: int = 5000
    # Teto de comentários LIDOS da API por execução, gravados ou não. Só pesa com o
    # termo de pesquisa, que descarta localmente: sem ele, um termo raro faria a
    # coleta paginar o vídeo inteiro. 20.000 lidos = 200 unidades de cota, no máximo.
    worker_max_comentarios_lidos_por_execucao: int = 20000
    youtube_timeout_seconds: int = 30

    # --- Cota diária da YouTube Data API (ADR-015 de docs/BANCO.md) ---------------
    # O Google dá 10.000 unidades por dia por projeto, e a chave é uma só: todas as
    # empresas dividem. Ver `services/cota.py` para a regra completa.
    youtube_cota_diaria: int = 10000
    # Margem que o app nunca gasta: cobre o que a mesma chave consome fora daqui
    # (teste manual, scripts do ml/) e a imprecisão da nossa contagem.
    youtube_cota_reserva: int = 500
    # A parte do dia garantida a cada empresa, mesmo com o dia cheio.
    youtube_cota_fatia_por_empresa: int = 2000
    # Fração do dia até a qual uma empresa pode passar da própria fatia. Acima dela,
    # só sobra o que falta da fatia de cada uma: é o que impede uma empresa de
    # esgotar o dia das outras.
    youtube_cota_folga_compartilhada: float = 0.7

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

    @property
    def caminho_bertimbau(self) -> Path:
        """Onde procurar a pasta do BERTimbau, com o padrão do repositório.

        O padrão é onde o modelo oficial fica depois de sair do Colab (`ml/modelos/`,
        fora do git). No App Service a pasta `ml/` não existe: `BERTIMBAU_PATH` aponta
        para `/home/modelos/...`, que sobrevive a restart.
        """
        if self.bertimbau_path.strip():
            return Path(self.bertimbau_path.strip())
        return REPO_ROOT / "ml" / "modelos" / "bertimbau-2026-09-30"


HOSTS_LOCAIS = ("localhost", "127.0.0.1")
AVISO_FRONTEND_URL_LOCAL = (
    "FRONTEND_URL aponta para localhost em produção: links de convite e de "
    "redefinição de senha ficarão inválidos. Configure FRONTEND_URL com o domínio "
    "da Vercel (https, sem barra no fim)."
)


def avisar_configuracao_suspeita(config: Settings) -> bool:
    """WARNING no arranque para configuração que falha em silêncio. Devolve se avisou.

    `FRONTEND_URL` tem padrão de desenvolvimento (localhost): esquecida no App
    Service, a API sobe normalmente e só o e-mail sai com um link que não abre em
    lugar nenhum — já aconteceu com um convite. Não derruba o app: o resto funciona,
    e o dono ainda pode corrigir o link à mão.
    """
    if config.app_env != "production":
        return False
    if not any(host in config.frontend_url for host in HOSTS_LOCAIS):
        return False
    logger.warning(AVISO_FRONTEND_URL_LOCAL)
    return True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
