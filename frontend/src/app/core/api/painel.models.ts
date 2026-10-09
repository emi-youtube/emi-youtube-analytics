/**
 * Contrato de `GET /api/v1/painel` (tela Início, design/Home.png).
 *
 * É uma tela de resumo: um endpoint só, montado pelo servidor. A alternativa
 * seria a tela disparar cinco requisições e somar na mão — o que colocaria
 * regra de negócio no frontend e mudaria de resultado conforme a ordem das
 * respostas.
 */

import { DistribuicaoSentimento, VersaoModelo } from './dominio.models';
import { StatusExecucao } from './execucoes.models';

/** Cartão preto do topo: a última execução concluída. */
export interface DestaqueExecucao {
  id_execucao: number;
  nome_modelo_analise: string;
  concluido_em: string | null;
  total_comentarios: number;
  total_videos: number;
  total_temas: number;
  distribuicao: DistribuicaoSentimento;
}

/** Linha da lista "Seus modelos". */
export interface ModeloNoPainel {
  id_modelo: number;
  nome: string;
  total_videos: number;
  /** Status da execução mais recente, ou `null` se nunca executou. */
  status_ultima_execucao: StatusExecucao | null;
  ultima_execucao_em: string | null;
  /** Preenchido quando a última execução terminou em `erro`. */
  motivo_da_falha: string | null;
  /** Execução concluída mais recente, para o link de resultados. */
  id_execucao_concluida: number | null;
  /**
   * Preenchido quando a última execução espera a cota diária da YouTube API renovar:
   * é a hora em que a coleta volta sozinha (ADR-015).
   */
  retoma_em?: string | null;
}

/** Cartão "No total". */
export interface TotaisUsuario {
  comentarios_analisados: number;
  execucoes_concluidas: number;
  videos_acompanhados: number;
}

/**
 * Cartão "Cota do YouTube hoje".
 *
 * O consumo é o que o worker de coleta registrou (`uso_cota_youtube`, ADR-015), somado
 * entre as empresas: a cota é do projeto e a chave é uma só. Um agregado, sem dado de
 * empresa nenhuma. Com a cota esgotada a coleta não falha, espera a renovação.
 */
export interface CotaYoutube {
  unidades_usadas: number;
  unidades_limite: number;
  /** ISO 8601 — a cota da YouTube API renova à meia-noite do Pacífico. */
  renova_em: string;
}

/** Resposta de `GET /api/v1/painel`. */
export interface ResumoPainel {
  /** `null` quando o usuário ainda não concluiu nenhuma execução. */
  destaque: DestaqueExecucao | null;
  modelos: ModeloNoPainel[];
  totais: TotaisUsuario;
  cota_youtube: CotaYoutube | null;
  /** Versão do classificador em uso (VERSOES_MODELO com status `ativo`). */
  versao_modelo: VersaoModelo | null;
}
