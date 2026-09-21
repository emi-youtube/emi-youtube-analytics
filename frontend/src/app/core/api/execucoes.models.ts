/** Espelha `backend/app/schemas/execucao.py`. */

/** Mesmos valores do CHECK `ck_execucoes_status`. */
export type StatusExecucao = 'pendente' | 'processando' | 'concluida' | 'erro';

export interface Execucao {
  id_execucao: number;
  id_modelo: number;
  status: StatusExecucao;
  iniciado_em: string | null;
  concluido_em: string | null;
}

/** Corpo de `POST /execucoes` — o resto a execução deriva do modelo. */
export interface ExecucaoCreate {
  id_modelo: number;
}

/**
 * Status em que a execução ainda pode mudar sozinha.
 *
 * É o mesmo par de `STATUS_ATIVOS` em `backend/app/services/execucao.py`, e
 * responde a duas perguntas da tela: até quando continuar o polling e quando o
 * modelo está ocupado para um novo disparo.
 */
const ATIVOS: readonly StatusExecucao[] = ['pendente', 'processando'];

export function estaAtiva(status: StatusExecucao): boolean {
  return ATIVOS.includes(status);
}

export const ROTULOS_STATUS: Record<StatusExecucao, string> = {
  pendente: 'Pendente',
  processando: 'Processando',
  concluida: 'Concluída',
  erro: 'Erro',
};
