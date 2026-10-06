/** Espelha `backend/app/schemas/conta.py` (ADR-012). */

import { Papel, PapelEmpresa } from '../auth/auth.models';

export interface MeusDados {
  nome: string;
  email: string;
  empresa: { nome: string };
  papel: Papel;
  papel_empresa: PapelEmpresa;
  criado_em: string;
  aceites_termos: { versao_termos: string; aceito_em: string }[];
  modelos_criados: { nome: string; criado_em: string }[];
}
