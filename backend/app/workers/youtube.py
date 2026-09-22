"""Cliente da YouTube Data API v3 usado pelo worker de coleta.

Custo de cota (CLAUDE.md regra 4): `commentThreads.list` e `videos.list` custam
1 unidade por chamada; `search.list` custa 100. Este cliente recusa `search` na
porta de entrada — os IDs de vídeo vêm curados nos filtros do modelo.

LGPD (CLAUDE.md regra 2): o autor do comentário é convertido em hash aqui dentro,
no ponto mais próximo possível da API. Nada acima desta camada chega a ver o
nome, o canal ou o ID original de quem comentou.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.core.security import hash_token

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"

# A chave viaja no cabeçalho, NUNCA na query string. Na query ela entra na URL, e a
# URL vaza em toda parte: log do httpx em INFO, log de proxy, mensagem de exceção,
# APM. O Google aceita os dois formatos e documenta este como o preferido.
CABECALHO_CHAVE = "X-Goog-Api-Key"

# videos.list aceita no máximo 50 IDs por chamada.
MAX_IDS_POR_CHAMADA = 50
# commentThreads.list aceita no máximo 100 resultados por página.
MAX_COMENTARIOS_POR_PAGINA = 100

RECURSO_PROIBIDO = "search"


class ErroYouTube(Exception):
    """Base dos erros do cliente."""


class ErroTransitorio(ErroYouTube):
    """429, 5xx ou timeout: vale repetir com backoff."""


class ErroPermanente(ErroYouTube):
    """Chave inválida, vídeo inexistente, cota estourada: repetir não resolve."""


class ComentariosDesabilitados(ErroYouTube):
    """O vídeo existe, mas tem comentários desativados — não é falha da execução."""


@dataclass(frozen=True)
class VideoColetado:
    youtube_video_id: str
    titulo: str
    canal: str
    publicado_em: datetime | None
    visualizacoes: int
    curtidas: int


@dataclass(frozen=True)
class ComentarioColetado:
    youtube_comment_id: str
    autor_hash: str
    texto: str
    publicado_em: datetime | None


def _para_datetime(valor: str | None) -> datetime | None:
    """Converte o ISO-8601 da API (`...Z`) em datetime com timezone."""
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None


def _para_int(valor: str | int | None) -> int:
    """Contadores vêm como string e somem quando o dono do vídeo os esconde."""
    try:
        return int(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _motivo_do_erro(resposta: httpx.Response) -> str:
    try:
        erros = resposta.json()["error"]["errors"]
        return str(erros[0].get("reason", ""))
    except (ValueError, KeyError, IndexError):
        return ""


class ClienteYouTube:
    """Só os dois endpoints baratos: `videos.list` e `commentThreads.list`."""

    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http = http

    async def _get(self, recurso: str, params: dict) -> dict:
        if recurso == RECURSO_PROIBIDO:
            # Guarda de última instância: 100 unidades de cota contra 1 dos outros
            # endpoints estoura a cota diária em poucas execuções.
            raise ErroPermanente(
                "search.list é proibido no projeto (CLAUDE.md regra 4): use IDs de vídeo curados."
            )

        try:
            resposta = await self._http.get(
                f"{API_BASE}/{recurso}",
                params=params,
                headers={CABECALHO_CHAVE: self._api_key},
            )
        except httpx.TimeoutException as erro:
            raise ErroTransitorio(f"timeout em {recurso}: {erro}") from erro
        except httpx.TransportError as erro:
            raise ErroTransitorio(f"falha de rede em {recurso}: {erro}") from erro

        if resposta.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise ErroTransitorio(f"429 em {recurso}")

        if resposta.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ErroTransitorio(f"{resposta.status_code} em {recurso}")

        if resposta.status_code >= httpx.codes.BAD_REQUEST:
            motivo = _motivo_do_erro(resposta)
            if motivo == "commentsDisabled":
                raise ComentariosDesabilitados(motivo)
            raise ErroPermanente(f"{resposta.status_code} em {recurso} (motivo={motivo or '?'})")

        return resposta.json()

    async def listar_videos(self, youtube_video_ids: Sequence[str]) -> list[VideoColetado]:
        """Metadados dos vídeos. IDs que não existem simplesmente não voltam."""
        coletados: list[VideoColetado] = []

        for inicio in range(0, len(youtube_video_ids), MAX_IDS_POR_CHAMADA):
            lote = youtube_video_ids[inicio : inicio + MAX_IDS_POR_CHAMADA]
            dados = await self._get(
                "videos",
                {"part": "snippet,statistics", "id": ",".join(lote), "maxResults": len(lote)},
            )

            for item in dados.get("items", []):
                snippet = item.get("snippet", {})
                estatisticas = item.get("statistics", {})
                coletados.append(
                    VideoColetado(
                        youtube_video_id=item["id"],
                        titulo=snippet.get("title", ""),
                        canal=snippet.get("channelTitle", ""),
                        publicado_em=_para_datetime(snippet.get("publishedAt")),
                        visualizacoes=_para_int(estatisticas.get("viewCount")),
                        curtidas=_para_int(estatisticas.get("likeCount")),
                    )
                )

        return coletados

    async def listar_comentarios(
        self, youtube_video_id: str, limite: int
    ) -> list[ComentarioColetado]:
        """Comentários de topo do vídeo, paginando até `limite`.

        Levanta `ComentariosDesabilitados` quando o vídeo tem comentários desativados;
        quem chama decide o que fazer (o worker registra o vídeo com zero e segue).
        """
        coletados: list[ComentarioColetado] = []
        pagina: str | None = None

        while len(coletados) < limite:
            params = {
                "part": "snippet",
                "videoId": youtube_video_id,
                "maxResults": min(MAX_COMENTARIOS_POR_PAGINA, limite - len(coletados)),
                "textFormat": "plainText",
            }
            if pagina:
                params["pageToken"] = pagina

            dados = await self._get("commentThreads", params)

            for item in dados.get("items", []):
                comentario = item["snippet"]["topLevelComment"]
                snippet = comentario["snippet"]
                coletados.append(
                    ComentarioColetado(
                        youtube_comment_id=comentario["id"],
                        autor_hash=_autor_hash(snippet),
                        texto=snippet.get("textDisplay", ""),
                        publicado_em=_para_datetime(snippet.get("publishedAt")),
                    )
                )

            pagina = dados.get("nextPageToken")
            if not pagina:
                break

        return coletados


def _autor_hash(snippet: dict) -> str:
    """SHA-256 do identificador do autor — o valor cru morre aqui.

    Prefere o ID do canal, que é estável; cai para o nome exibido só quando a API
    omite o canal (acontece em comentário de conta removida).
    """
    canal = (snippet.get("authorChannelId") or {}).get("value")
    return hash_token(canal or snippet.get("authorDisplayName", ""))
