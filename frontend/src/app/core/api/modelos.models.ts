/**
 * Espelha `backend/app/schemas/modelo_analise.py`.
 *
 * Nomes de campo em português por serem o contrato da API (o backend usa
 * `nome`, `termo_pesquisa`, `filtros`); o resto do frontend segue em inglês.
 */

/**
 * Conteúdo da coluna JSONB `MODELOS_ANALISE.filtros`.
 *
 * O schema do backend é `extra="allow"`, então chave nova não precisa de
 * migration. Em compensação o worker de coleta só entende as chaves de
 * `CHAVES_CONHECIDAS` em `backend/app/workers/coleta.py` — as demais são
 * registradas e ignoradas com um aviso no log.
 */
export interface FiltrosModelo {
  /** IDs do YouTube curados à mão. É o que a coleta de fato usa. */
  videos?: string[];
  /** Ainda não expandido pelo worker; o formulário não oferece o campo. */
  canais?: string[];
  /**
   * Data mínima do comentário (`YYYY-MM-DD`), a partir da meia-noite de
   * Brasília. A coleta descarta os anteriores e para de paginar ao passar dela.
   */
  publicado_apos?: string;
  /**
   * Máximo de comentários da execução (soma de todos os vídeos). Inteiro >= 1;
   * acima do teto do worker (5.000), vale o teto.
   */
  limite_comentarios?: number;
  [chave: string]: unknown;
}

export interface ModeloAnalise {
  id_modelo: number;
  id_usuario: number;
  nome: string;
  termo_pesquisa: string;
  filtros: FiltrosModelo | null;
  criado_em: string;
  /** Nome de quem criou (ADR-013). Só o nome: o e-mail do colega não vem. */
  autor_nome: string;
  /** Se quem está logado pode editar e apagar: o autor ou um dono da empresa. */
  pode_alterar: boolean;
}

/** Corpo de `POST /modelos-analise`. */
export interface ModeloAnaliseCreate {
  nome: string;
  termo_pesquisa: string;
  filtros: FiltrosModelo | null;
}

/** Corpo de `PATCH /modelos-analise/{id}` — só o que muda. */
export type ModeloAnaliseUpdate = Partial<ModeloAnaliseCreate>;

/** Quantidade de vídeos curados no modelo. */
export function totalDeVideos(modelo: ModeloAnalise): number {
  return modelo.filtros?.videos?.length ?? 0;
}
