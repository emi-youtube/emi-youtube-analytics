/** Espelha `backend/app/schemas/admin.py` (papel global `admin`). */

export interface CotaDaEmpresa {
  id_empresa: number;
  nome: string;
  unidades_hoje: number;
  /** Soma do período pedido, hoje incluído. */
  unidades_periodo: number;
  /** Execuções paradas agora esperando a cota renovar (ADR-015). */
  execucoes_aguardando: number;
  /** Gastou hoje mais que a fatia garantida. */
  acima_da_fatia: boolean;
}

export interface ConsumoDoDia {
  /** `AAAA-MM-DD`, o dia da cota (fuso do Pacífico). */
  dia: string;
  unidades: number;
}

/** Resposta de `GET /api/v1/admin/cota-youtube`. */
export interface CotaAdmin {
  dia_da_cota: string;
  renova_em: string;
  limite: number;
  reserva: number;
  fatia_por_empresa: number;
  /** Até quantas unidades do dia vale a folga compartilhada. */
  teto_folga: number;
  usado_hoje: number;
  /** Unidades que a API disse já não existirem sem o app as ter gasto. */
  ajuste_hoje: number;
  dias: number;
  empresas: CotaDaEmpresa[];
  /** Um ponto por dia, do mais antigo a hoje. */
  historico: ConsumoDoDia[];
  pico_no_periodo: number;
  media_no_periodo: number;
}
