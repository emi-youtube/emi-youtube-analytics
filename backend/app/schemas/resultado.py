"""Schemas das rotas de resultado — o outro lado de `frontend/src/app/core/api/`.

O contrato foi escrito ANTES destes endpoints (`dominio.models.ts`,
`resultados.models.ts`, `comentarios.models.ts`), enquanto as telas rodavam com
mock. Aqui ele é implementado, **campo por campo e com o mesmo nome** — nome de
campo igual ao nome da coluna, em português, porque a banca compara com o DER.

Três pontos do contrato que este arquivo resolve de propósito:

- **`AnaliseSentimento.confianca` sempre vem `None`.** A coluna não existe no
  schema e não entra neste card. O campo fica no contrato (o TS já o documenta
  como pendente) para o selo "Revisão sugerida" não exigir mudança de forma
  quando a coluna chegar; hoje ele é nulo e a tela não mostra o selo.
- **`metricas_avaliacao` é nulo quando não há avaliação.** O classificador
  léxico grava proveniência (sha256 do recurso), não métrica: ele nunca foi
  avaliado contra o gabarito humano, que é o único válido (CLAUDE.md regra 6).
  Devolver a proveniência nesse campo faria a tela ler `f1_macro` inexistente;
  devolver `{}` seria lido como "avaliado e deu zero". Nulo é o que é verdade.
- **`temas` vem vazio.** Não existe worker de tópicos. As consultas de tema
  estão escritas e são exercitadas por teste, então acendem sozinhas quando o
  worker chegar — mas hoje TEMAS não tem linha e a lista é `[]`.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Sentimento = Literal["positivo", "negativo", "neutro"]
StatusVersaoModelo = Literal["ativo", "arquivado"]

# Os tipos de fato que o motor de insights sabe produzir (app/insights/fatos.py).
# Literal, e não `str`, para o `switch` exaustivo do Angular fechar no compilador.
TipoFato = Literal[
    "tema_mais_criticado",
    "tema_melhor_recebido",
    "video_muito_negativo",
    "concentracao_das_criticas",
    "variacao_de_sentimento",
    "evolucao_do_video",
]

# O que cabe em `FatoInsight.valores` — espelha `ValorFato` do TS.
ValorFato = str | int | float | bool | None


# --------------------------------------------------------------------------- linhas de tabela


class VideoResponse(BaseModel):
    """Tabela VIDEOS."""

    model_config = ConfigDict(from_attributes=True)

    id_video: int
    id_execucao: int
    youtube_video_id: str
    titulo: str
    canal: str
    publicado_em: datetime | None
    visualizacoes: int
    curtidas: int


class ComentarioResponse(BaseModel):
    """Tabela COMENTARIOS.

    `autor_hash` viaja porque é a chave que liga comentários da mesma pessoa
    dentro de uma execução, e o contrato o declara. Nenhuma tela o imprime —
    o autor original nunca foi persistido (CLAUDE.md regra 2).
    """

    model_config = ConfigDict(from_attributes=True)

    id_comentario: int
    id_video: int
    youtube_comment_id: str
    autor_hash: str
    texto: str
    publicado_em: datetime | None


class AnaliseSentimentoResponse(BaseModel):
    """Tabela ANALISES_SENTIMENTO. `confianca` é sempre nulo — ver cabeçalho."""

    model_config = ConfigDict(from_attributes=True)

    id_analise: int
    id_comentario: int
    id_versao_modelo: int
    sentimento: Sentimento
    tema: str | None
    justificativa: str | None
    processado_em: datetime
    confianca: float | None = None


class TemaResponse(BaseModel):
    """Tabela TEMAS."""

    model_config = ConfigDict(from_attributes=True)

    id_tema: int
    id_execucao: int
    rotulo_tema: str
    palavras_chave: list[str] | None


class MetricasAvaliacao(BaseModel):
    """O recorte de `VERSOES_MODELO.metricas_avaliacao` que a tela sabe ler.

    `f1_macro` é obrigatório: é a métrica que importa no projeto (CLAUDE.md
    regra 8) e o que distingue "versão avaliada" de "versão que só tem
    proveniência". Um JSONB sem ela não vira este objeto — vira `None`.
    """

    f1_macro: float
    acuracia: float | None = None
    f1_por_classe: dict[str, float] | None = None
    exemplos_teste: int | None = None


class VersaoModeloResponse(BaseModel):
    """Tabela VERSOES_MODELO, com `em_uso_desde` calculado."""

    id_versao: int
    nome_modelo: str
    versao: str
    metricas_avaliacao: MetricasAvaliacao | None
    status: StatusVersaoModelo
    # Não é coluna: a primeira vez que esta versão classificou algo desta
    # execução (MIN de processado_em). A tela mostra "em uso desde".
    em_uso_desde: datetime | None = None


# --------------------------------------------------------------------------- agregações


class DistribuicaoSentimento(BaseModel):
    """Contagem por sentimento. `total` vem pronto para a tela não somar errado."""

    positivo: int = 0
    neutro: int = 0
    negativo: int = 0
    total: int = 0


class AlcanceExecucao(BaseModel):
    """Somas de VIDEOS da execução, mais a taxa de engajamento."""

    visualizacoes: int
    curtidas: int
    comentarios: int
    comentarios_por_mil_views: float


# --------------------------------------------------------------------------- composições


class VideoResumido(BaseModel):
    """Recorte de VIDEOS que o comentário carrega junto."""

    model_config = ConfigDict(from_attributes=True)

    id_video: int
    youtube_video_id: str
    titulo: str


class TemaDoComentario(BaseModel):
    """TEMAS.rotulo_tema + COMENTARIO_TEMA.peso."""

    id_tema: int
    rotulo_tema: str
    peso: float


class ComentarioAnalisado(BaseModel):
    """Comentário com tudo que a tela mostra dele.

    Aninhado porque cada parte é uma linha de tabela identificável: quem lê a
    resposta sabe de qual tabela saiu cada campo, sem achatar tudo num objeto.
    """

    comentario: ComentarioResponse
    analise: AnaliseSentimentoResponse
    video: VideoResumido
    temas: list[TemaDoComentario] = []


class VideoComSentimento(BaseModel):
    video: VideoResponse
    distribuicao: DistribuicaoSentimento


class TemaComSentimento(BaseModel):
    tema: TemaResponse
    distribuicao: DistribuicaoSentimento


# --------------------------------------------------------------------------- insights


class AmostraInsight(BaseModel):
    tamanho: int
    minimo_exigido: int


class OrigemInsight(BaseModel):
    id_execucoes: list[int] = []
    id_tema: int | None = None
    id_video: int | None = None
    youtube_video_id: str | None = None


class FatoInsight(BaseModel):
    """Um achado do motor de insights, serializado como FATO — não como frase.

    `texto` vem do servidor porque a frase faz parte da análise (se a regra
    muda, a frase muda junto, num lugar só), mas acompanhado do que a gerou:
    a tela ordena, filtra e monta link a partir de `tipo`, `valores` e `origem`.
    """

    tipo: TipoFato
    valores: dict[str, ValorFato] = {}
    amostra: AmostraInsight
    origem: OrigemInsight
    texto: str


class PontoDeAtencao(BaseModel):
    """DEPRECIADO — substituído por `insights`. Ver `resultados.models.ts`."""

    id_tema: int
    rotulo_tema: str
    texto: str


# --------------------------------------------------------------------------- respostas


class ResultadoExecucao(BaseModel):
    """Resposta de `GET /api/v1/execucoes/{id}/resultado`."""

    id_execucao: int
    id_modelo: int
    nome_modelo_analise: str
    concluido_em: datetime | None
    distribuicao: DistribuicaoSentimento
    alcance: AlcanceExecucao
    videos: list[VideoComSentimento]
    temas: list[TemaComSentimento]
    comentarios_representativos: list[ComentarioAnalisado]
    insights: list[FatoInsight]
    insights_da_campanha: list[FatoInsight]
    ponto_de_atencao: PontoDeAtencao | None
    # Nulo só na execução que não classificou nada (todos os vídeos com
    # comentário desabilitado) num banco onde nenhuma versão foi registrada
    # ainda. A tela precisa aguentar isso sem quebrar.
    versao_modelo: VersaoModeloResponse | None


class ResultadoDisponivel(BaseModel):
    """Item de `GET /api/v1/execucoes/resultados` — só o suficiente para escolher."""

    id_execucao: int
    id_modelo: int
    nome_modelo_analise: str
    concluido_em: datetime | None
    distribuicao: DistribuicaoSentimento
    total_videos: int
    total_temas: int


class PaginaComentarios(BaseModel):
    """Resposta de `GET /api/v1/execucoes/{id}/comentarios`."""

    itens: list[ComentarioAnalisado]
    total: int
    pagina: int
    tamanho: int
    # Contagem por sentimento DENTRO do filtro atual, IGNORANDO o próprio
    # filtro de sentimento: é o que mantém os chips "Positivo · 160" visíveis
    # depois de o usuário clicar num deles.
    contagem_por_sentimento: DistribuicaoSentimento
