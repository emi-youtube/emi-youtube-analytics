"""Schemas de `GET /api/v1/painel` (tela Início) — ver `painel.models.ts`.

É uma tela de resumo servida por UM endpoint. A alternativa seria a tela
disparar cinco requisições e somar na mão, o que colocaria regra de negócio no
frontend e mudaria de resultado conforme a ordem das respostas.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.resultado import DistribuicaoSentimento, VersaoModeloResponse

StatusExecucao = Literal["pendente", "processando", "concluida", "erro"]


class DestaqueExecucao(BaseModel):
    """Cartão preto do topo: a última execução concluída do usuário."""

    id_execucao: int
    nome_modelo_analise: str
    concluido_em: datetime | None
    total_comentarios: int
    total_videos: int
    total_temas: int
    distribuicao: DistribuicaoSentimento


class ModeloNoPainel(BaseModel):
    """Linha da lista "Seus modelos"."""

    id_modelo: int
    nome: str
    # Quantos vídeos a campanha acompanha. Sai de `filtros.videos`, e não de
    # VIDEOS: VIDEOS só existe depois da coleta, e a lista tem de mostrar
    # "3 vídeos" num modelo que nunca executou. Quando VIDEOS_MONITORADOS
    # existir (CLAUDE.md Seção 11), a contagem migra para lá.
    total_videos: int
    status_ultima_execucao: StatusExecucao | None
    ultima_execucao_em: datetime | None
    motivo_da_falha: str | None
    id_execucao_concluida: int | None


class TotaisUsuario(BaseModel):
    """Cartão "No total"."""

    comentarios_analisados: int
    execucoes_concluidas: int
    videos_acompanhados: int


class CotaYoutube(BaseModel):
    """Cartão "Cota do YouTube hoje".

    NÃO sai de tabela nenhuma: o consumo é contabilizado pela YouTube Data API
    contra a chave do projeto, e o worker de coleta não registra o que gastou.
    Enquanto ninguém registrar, o endpoint devolve `null` e a tela esconde o
    cartão — o que é melhor que estampar um número inventado num painel.
    """

    unidades_usadas: int
    unidades_limite: int
    renova_em: datetime


class ResumoPainel(BaseModel):
    destaque: DestaqueExecucao | None
    modelos: list[ModeloNoPainel]
    totais: TotaisUsuario
    cota_youtube: CotaYoutube | None
    versao_modelo: VersaoModeloResponse | None
