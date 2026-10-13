/**
 * Contrato de `GET /api/v1/execucoes/{id}/comentarios` (tela Comentários,
 * design/Comentarios.png).
 */

import { DistribuicaoSentimento, Sentimento } from './dominio.models';
import { ComentarioAnalisado } from './resultados.models';

/** Vira query string. Campo ausente = filtro não aplicado. */
export interface FiltroComentarios {
  /** Busca no texto do comentário (COMENTARIOS.texto). */
  busca?: string;
  /** Filtra por COMENTARIO_TEMA.id_tema. */
  id_tema?: number;
  /** Filtra por COMENTARIOS.id_video. */
  id_video?: number;
  sentimento?: Sentimento;
  /** 1-based, como aparece na tela. */
  pagina: number;
  tamanho: number;
}

/** Resposta paginada. */
export interface PaginaComentarios {
  itens: ComentarioAnalisado[];
  /** Total que casa com o filtro — não o total da execução. */
  total: number;
  pagina: number;
  tamanho: number;
  /**
   * Contagem por sentimento DENTRO do filtro atual, menos o próprio filtro de
   * sentimento: é o que os chips "Positivo · 160 / Neutro · 198" mostram, e
   * eles precisam continuar visíveis depois de escolher um deles.
   */
  contagem_por_sentimento: DistribuicaoSentimento;
  /** Os mesmos campos de `ResultadoExecucao` (ADR-015). */
  comentarios_disponiveis_ate?: string | null;
  comentarios_apagados_em?: string | null;
}

export const TAMANHO_PAGINA_PADRAO = 5;
