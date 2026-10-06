/** Espelha `backend/app/schemas/empresa.py`. */

import { PapelEmpresa } from '../auth/auth.models';

export interface Membro {
  id_usuario: number;
  nome: string;
  email: string;
  papel_empresa: PapelEmpresa;
  criado_em: string;
}

export interface ConviteCreate {
  email: string;
  papel_empresa: PapelEmpresa;
}

/** Convite pendente como a lista do dono mostra. Nunca traz o token. */
export interface Convite {
  id_convite: number;
  email: string;
  papel_empresa: PapelEmpresa;
  expira_em: string;
  criado_em: string;
}

/** Resposta da criação: a ÚNICA vez em que o link aparece. */
export interface ConviteCriado extends Convite {
  link: string;
}
