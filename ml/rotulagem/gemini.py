"""Cliente mínimo da Gemini para a rotulagem fraca. OFFLINE, só no `ml/`.

CLAUDE.md regra 3: a Gemini não roda em produção. Este módulo vive em `ml/` e o
backend nunca o importa — a chave nem existe no ambiente de produção.

A chave vai no cabeçalho `x-goog-api-key`, NUNCA na query string. Mesma lição do
cliente da YouTube API: na query ela entra na URL, e a URL vai parar no log do
httpx em INFO, em log de proxy e em traceback.

Sem SDK de propósito: uma chamada REST com `urllib` não acrescenta dependência ao
ambiente de treino e deixa explícito o que é enviado.
"""

import json
import logging
import random
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# A chave viaja aqui, nunca em `?key=`.
CABECALHO_CHAVE = "x-goog-api-key"

# Backoff para 429 (cota por minuto do free tier) e 5xx: 4, 8, 16, 32, 64s.
BACKOFF_BASE = 2
BACKOFF_EXPOENTE_INICIAL = 2
JITTER_MAXIMO = 1.0


class ErroGemini(Exception):
    """Base dos erros do cliente."""


class ErroTransitorio(ErroGemini):
    """429 ou 5xx: vale repetir com backoff."""


class ErroPermanente(ErroGemini):
    """Chave inválida, modelo inexistente, requisição malformada."""


class ClienteGemini:
    def __init__(self, api_key: str, modelo: str, temperatura: float = 0.0) -> None:
        self._api_key = api_key
        self._modelo = modelo
        self._temperatura = temperatura
        self.chamadas = 0

    @property
    def modelo(self) -> str:
        return self._modelo

    def _corpo(self, instrucao_sistema: str, prompt: str) -> dict:
        return {
            "systemInstruction": {"parts": [{"text": instrucao_sistema}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                # Temperatura 0: a rotulagem precisa ser reprodutível. Rodar de novo
                # o mesmo lote tem que dar o mesmo rótulo, senão o corpus muda sozinho.
                "temperature": self._temperatura,
                # Obriga JSON na saída, em vez de torcer para o modelo obedecer o
                # "responda só com JSON" do prompt.
                "responseMimeType": "application/json",
            },
        }

    def _requisitar(self, corpo: dict) -> dict:
        url = f"{API_BASE}/{self._modelo}:generateContent"
        requisicao = urllib.request.Request(
            url,
            data=json.dumps(corpo).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                CABECALHO_CHAVE: self._api_key,
            },
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=120) as resposta:
                self.chamadas += 1
                return json.load(resposta)
        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode("utf-8", "replace")[:300]
            if erro.code == 429 or erro.code >= 500:
                raise ErroTransitorio(f"HTTP {erro.code}: {detalhe}") from erro
            raise ErroPermanente(f"HTTP {erro.code}: {detalhe}") from erro
        except urllib.error.URLError as erro:
            raise ErroTransitorio(f"falha de rede: {erro}") from erro

    def gerar(self, instrucao_sistema: str, prompt: str, max_tentativas: int = 5) -> str:
        """Devolve o texto da resposta, repetindo em erro transitório."""
        corpo = self._corpo(instrucao_sistema, prompt)

        for tentativa in range(max_tentativas):
            try:
                dados = self._requisitar(corpo)
            except ErroTransitorio as erro:
                if tentativa == max_tentativas - 1:
                    raise
                espera = BACKOFF_BASE ** (BACKOFF_EXPOENTE_INICIAL + tentativa)
                espera += random.uniform(0, JITTER_MAXIMO)
                logger.warning(
                    "erro transitorio (tentativa %s/%s), esperando %.1fs: %s",
                    tentativa + 1,
                    max_tentativas,
                    espera,
                    erro,
                )
                time.sleep(espera)
                continue

            try:
                return dados["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as erro:
                # Resposta sem candidato costuma ser bloqueio de safety filter.
                motivo = dados.get("promptFeedback", {}).get("blockReason", "?")
                raise ErroPermanente(
                    f"resposta sem conteudo (blockReason={motivo}): {str(dados)[:300]}"
                ) from erro

        raise ErroTransitorio("tentativas esgotadas")
