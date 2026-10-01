"""Cliente da YouTube Data API v3 usado pelo worker de coleta.

Custo de cota (CLAUDE.md regra 4): `commentThreads.list` e `videos.list` custam
1 unidade por chamada; `search.list` custa 100. Este cliente recusa `search` na
porta de entrada — os IDs de vídeo vêm curados nos filtros do modelo.

LGPD (CLAUDE.md regra 2): o autor do comentário é convertido em hash aqui dentro,
no ponto mais próximo possível da API. Nada acima desta camada chega a ver o
nome, o canal ou o ID original de quem comentou.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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


@dataclass
class LoteComentarios:
    """O que `listar_comentarios` devolve: os aceitos e a conta do que foi lido.

    `lidos` é o que saiu da API (e custou cota); `comentarios` é o que passou nos
    filtros. A diferença aparece no painel como o recorte da coleta.
    """

    comentarios: list[ComentarioColetado] = field(default_factory=list)
    lidos: int = 0
    descartados_por_data: int = 0
    descartados_por_termo: int = 0
    # Paginação interrompida ao passar da data mínima (ordem do mais novo para o
    # mais antigo), e não por fim de vídeo ou por limite.
    parou_na_data: bool = False


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
        self,
        youtube_video_id: str,
        limite: int,
        *,
        publicado_apos: datetime | None = None,
        aceitar_texto: Callable[[str], bool] | None = None,
        max_lidos: int | None = None,
    ) -> LoteComentarios:
        """Comentários de topo do vídeo, paginando até `limite` ACEITOS.

        - `publicado_apos`: descarta os anteriores. A API devolve do mais recente
          para o mais antigo (`order=time`, pedido explicitamente; conferido contra a
          API real: 351 comentários de dois vídeos, zero inversões), então o primeiro
          comentário anterior à data encerra a paginação: as páginas seguintes só
          teriam comentários mais antigos e custariam cota à toa.
        - `aceitar_texto`: filtro local sobre o texto (o termo de pesquisa).
        - `max_lidos`: teto do que sai da API, aceito ou não — protege a cota quando
          o filtro de texto descarta quase tudo.

        Levanta `ComentariosDesabilitados` quando o vídeo tem comentários desativados;
        quem chama decide o que fazer (o worker registra o vídeo com zero e segue).
        """
        lote = LoteComentarios()
        pagina: str | None = None
        teto_leitura = max_lidos if max_lidos is not None else float("inf")
        # Sem filtro, pedir só o que falta poupa transferência; com filtro, a página
        # cheia custa a mesma unidade de cota e rende mais candidatos.
        filtra = publicado_apos is not None or aceitar_texto is not None

        while len(lote.comentarios) < limite and lote.lidos < teto_leitura:
            faltam = MAX_COMENTARIOS_POR_PAGINA if filtra else limite - len(lote.comentarios)
            params = {
                "part": "snippet",
                "videoId": youtube_video_id,
                "maxResults": int(
                    min(MAX_COMENTARIOS_POR_PAGINA, faltam, teto_leitura - lote.lidos)
                ),
                "textFormat": "plainText",
                "order": "time",
            }
            if pagina:
                params["pageToken"] = pagina

            dados = await self._get("commentThreads", params)

            for item in dados.get("items", []):
                # Os dois tetos valem item a item, não só por página: não se confia
                # que a resposta respeite o `maxResults` pedido.
                if len(lote.comentarios) >= limite or lote.lidos >= teto_leitura:
                    break
                lote.lidos += 1
                comentario = item["snippet"]["topLevelComment"]
                snippet = comentario["snippet"]
                publicado_em = _para_datetime(snippet.get("publishedAt"))
                texto = snippet.get("textDisplay", "")

                if publicado_apos is not None and (
                    publicado_em is None or publicado_em < publicado_apos
                ):
                    # Sem data não há como provar que é posterior: fica de fora.
                    lote.descartados_por_data += 1
                    if publicado_em is not None:
                        lote.parou_na_data = True
                    continue
                if aceitar_texto is not None and not aceitar_texto(texto):
                    lote.descartados_por_termo += 1
                    continue

                lote.comentarios.append(
                    ComentarioColetado(
                        youtube_comment_id=comentario["id"],
                        autor_hash=_autor_hash(snippet),
                        texto=texto,
                        publicado_em=publicado_em,
                    )
                )

            pagina = dados.get("nextPageToken")
            if not pagina or lote.parou_na_data:
                break

        return lote


def _autor_hash(snippet: dict) -> str:
    """SHA-256 do identificador do autor — o valor cru morre aqui.

    Prefere o ID do canal, que é estável; cai para o nome exibido só quando a API
    omite o canal (acontece em comentário de conta removida).
    """
    canal = (snippet.get("authorChannelId") or {}).get("value")
    return hash_token(canal or snippet.get("authorDisplayName", ""))
