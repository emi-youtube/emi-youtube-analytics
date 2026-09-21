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
 * migration. Em compensação o worker de coleta só entende `videos` e `canais`
 * (ver `CHAVES_CONHECIDAS` em `backend/app/workers/coleta.py`) — as demais são
 * registradas e ignoradas com um aviso no log.
 */
export interface FiltrosModelo {
  /** IDs do YouTube curados à mão. É o que a coleta de fato usa. */
  videos?: string[];
  /** Ainda não expandido pelo worker; o formulário não oferece o campo. */
  canais?: string[];
  /** Data mínima do comentário (`YYYY-MM-DD`). Ainda não lida pelo worker. */
  publicado_apos?: string;
  /** Teto de comentários pedido pelo usuário. Ainda não lido pelo worker. */
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
