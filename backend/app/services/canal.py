"""Confere, ao salvar o modelo, que os vídeos são de um canal só (III.E.2).

As políticas dos YouTube API Services (III.E.2) não permitem combinar num mesmo
resultado dados de canais de donos diferentes. A coleta já recusa a execução com
vídeos de mais de um canal (`workers/coleta.py`), mas só descobre isso depois do
clique em "Executar", e a execução termina em erro. Aqui a mesma regra roda no
salvamento: o usuário vê, no próprio formulário, quais vídeos são de qual canal.

O ID do vídeo não diz de que canal ele é. Descobrir exige `videos.list`, que só o
servidor pode chamar: a chave da API não vai para o navegador.

Custo: uma chamada de `videos.list` (1 unidade a cada 50 vídeos), cobrada da cota da
empresa como qualquer outra. Modelo com um vídeo só não gasta nada.

Esta conferência é uma ajuda ao usuário, não a garantia. Se a API falhar, demorar ou
a empresa estiver sem cota, o modelo é salvo assim mesmo e a regra continua valendo
na coleta. É só uma chamada de metadados, curta e com timeout próprio: nenhum
comentário é coletado dentro da requisição (CLAUDE.md, Seção 10).

Nada da resposta é gravado. O nome dos canais só aparece na mensagem de erro e não
entra no log, porque é dado da API (regra dos 30 dias).
"""

import logging
import math
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import cota
from app.workers.youtube import (
    MAX_IDS_POR_CHAMADA,
    ClienteYouTube,
    CotaEsgotada,
    ErroYouTube,
    VideoColetado,
)

logger = logging.getLogger(__name__)

# Bem menor que o timeout do worker: aqui tem uma pessoa esperando o botão responder.
TIMEOUT_CONFERENCIA_SEGUNDOS = 5.0

# Quantos IDs mostrar por canal na mensagem; o resto vira "e mais N".
IDS_NA_MENSAGEM = 3

# `loc` no mesmo formato da validação do FastAPI, para o formulário pôr a mensagem
# embaixo do campo dos vídeos, e não no topo da tela.
LOC_VIDEOS = ["body", "filtros", "videos"]
TIPO_CANAIS_DIFERENTES = "canais_diferentes"


async def get_cliente_youtube() -> AsyncIterator[ClienteYouTube | None]:
    """Dependency: um cliente da YouTube API para a duração da requisição.

    Sem chave configurada devolve None, e a conferência não roda. Os testes trocam
    esta dependency, para nenhum teste tocar a rede.
    """
    if not settings.youtube_api_key:
        yield None
        return
    async with httpx.AsyncClient(timeout=TIMEOUT_CONFERENCIA_SEGUNDOS) as http:
        yield ClienteYouTube(settings.youtube_api_key, http)


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def _descrever_canal(nome: str, videos: list[VideoColetado]) -> str:
    ids = [v.youtube_video_id for v in videos[:IDS_NA_MENSAGEM]]
    resto = len(videos) - len(ids)
    lista = ", ".join(ids) + (f" e mais {resto}" if resto else "")
    return f"{nome or 'canal sem nome'} ({_plural(len(videos), 'vídeo', 'vídeos')}: {lista})"


def mensagem_canais_diferentes(por_canal: dict[str, list[VideoColetado]]) -> str:
    """A frase do formulário, com o canal de cada vídeo. O maior canal vem primeiro."""
    grupos = sorted(por_canal.values(), key=lambda grupo: -len(grupo))
    descricoes = [_descrever_canal(grupo[0].canal, grupo) for grupo in grupos]
    juntas = ", ".join(descricoes[:-1]) + " e " + descricoes[-1]
    return (
        f"Os vídeos são de {len(grupos)} canais diferentes: {juntas}. Pelas regras da API "
        "do YouTube, uma análise só junta vídeos de um mesmo canal. Deixe aqui os vídeos "
        "de um canal e crie outro modelo para os demais."
    )


async def conferir_um_canal(
    db: AsyncSession,
    cliente: ClienteYouTube | None,
    id_empresa: int,
    youtube_video_ids: Sequence[str],
) -> None:
    """Levanta 422 se os vídeos forem de mais de um canal; em qualquer dúvida, deixa passar."""
    ids = list(dict.fromkeys(youtube_video_ids))
    if cliente is None or len(ids) < 2:
        return

    agora = datetime.now(UTC)
    custo = math.ceil(len(ids) / MAX_IDS_POR_CHAMADA)
    orcamento = await cota.orcamento_da_empresa(db, id_empresa, agora)
    if orcamento < custo:
        logger.info(
            "conferencia de canal pulada por falta de cota id_empresa=%s videos=%s",
            id_empresa,
            len(ids),
        )
        return

    videos: list[VideoColetado] | None = None
    with cliente.medir(orcamento) as medida:
        try:
            videos = await cliente.listar_videos(ids)
        except CotaEsgotada as erro:
            if erro.da_api:
                await cota.marcar_esgotada(db, agora)
            logger.warning("conferencia de canal sem cota id_empresa=%s", id_empresa)
        except (ErroYouTube, httpx.HTTPError, ValueError) as erro:
            # ValueError: resposta que não é JSON. Nenhuma falha aqui impede o salvamento.
            logger.warning(
                "conferencia de canal falhou, modelo salvo sem ela id_empresa=%s erro=%s",
                id_empresa,
                type(erro).__name__,
            )
    await cota.registrar_uso(db, id_empresa, medida.unidades, agora)

    if videos is None:
        return

    por_canal: dict[str, list[VideoColetado]] = {}
    for video in videos:
        if video.id_canal:
            por_canal.setdefault(video.id_canal, []).append(video)

    if len(por_canal) > 1:
        logger.info(
            "modelo recusado: videos de canais diferentes id_empresa=%s videos=%s canais=%s",
            id_empresa,
            len(ids),
            len(por_canal),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "loc": LOC_VIDEOS,
                    "msg": mensagem_canais_diferentes(por_canal),
                    "type": TIPO_CANAIS_DIFERENTES,
                }
            ],
        )
