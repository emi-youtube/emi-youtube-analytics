/**
 * Contrato de `GET /api/v1/execucoes/{id}/resultado` (tela Resultados,
 * design/Dashboard.png) e de `GET /api/v1/execucoes/resultados` (lista).
 *
 * Ver `dominio.models.ts` para as linhas de tabela reaproveitadas aqui.
 */

import {
  AnaliseSentimento,
  Comentario,
  DistribuicaoSentimento,
  Tema,
  Video,
  VersaoModelo,
} from './dominio.models';

/** Recorte de VIDEOS que o comentário carrega junto, para não repetir a linha inteira. */
export interface VideoResumido {
  id_video: number;
  youtube_video_id: string;
  titulo: string;
}

/** Um tema do comentário: TEMAS.rotulo_tema + COMENTARIO_TEMA.peso. */
export interface TemaDoComentario {
  id_tema: number;
  rotulo_tema: string;
  peso: number;
}

/**
 * Comentário com tudo que a tela precisa mostrar dele.
 *
 * Aninhado de propósito: cada parte é uma linha de tabela identificável, então
 * o backend monta isto com joins diretos e ninguém precisa adivinhar de onde
 * saiu cada campo.
 */
export interface ComentarioAnalisado {
  comentario: Comentario;
  analise: AnaliseSentimento;
  video: VideoResumido;
  /** De COMENTARIO_TEMA, do maior peso para o menor. */
  temas: TemaDoComentario[];
}

/** Linha de VIDEOS + as contagens daquele vídeo. */
export interface VideoComSentimento {
  video: Video;
  distribuicao: DistribuicaoSentimento;
}

/** Linha de TEMAS + as contagens daquele tema. */
export interface TemaComSentimento {
  tema: Tema;
  distribuicao: DistribuicaoSentimento;
}

/** Somas de VIDEOS da execução. */
export interface AlcanceExecucao {
  visualizacoes: number;
  curtidas: number;
  comentarios: number;
  /** comentarios / (visualizacoes / 1000). */
  comentarios_por_mil_views: number;
}

/**
 * Destaque textual do card "O que merece atenção".
 *
 * Vem pronto do servidor, e não montado na tela, porque a regra de qual tema
 * merece atenção é da análise — se mudar, muda em um lugar só.
 */
export interface PontoDeAtencao {
  id_tema: number;
  rotulo_tema: string;
  texto: string;
}

/** Resposta de `GET /api/v1/execucoes/{id}/resultado`. */
export interface ResultadoExecucao {
  id_execucao: number;
  id_modelo: number;
  /** MODELOS_ANALISE.nome — o título da tela. */
  nome_modelo_analise: string;
  concluido_em: string | null;
  distribuicao: DistribuicaoSentimento;
  alcance: AlcanceExecucao;
  videos: VideoComSentimento[];
  temas: TemaComSentimento[];
  /** Amostra escolhida pelo servidor: um positivo, um negativo, um neutro. */
  comentarios_representativos: ComentarioAnalisado[];
  ponto_de_atencao: PontoDeAtencao | null;
  /** Qual versão do BERTimbau classificou esta execução. */
  versao_modelo: VersaoModelo;
}

/** Item de `GET /api/v1/execucoes/resultados` — só o suficiente para escolher. */
export interface ResultadoDisponivel {
  id_execucao: number;
  id_modelo: number;
  nome_modelo_analise: string;
  concluido_em: string | null;
  distribuicao: DistribuicaoSentimento;
  total_videos: number;
  total_temas: number;
}
