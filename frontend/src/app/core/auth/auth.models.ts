/**
 * Espelha os schemas de `backend/app/schemas/auth.py`.
 *
 * Os nomes de campo ficam em português porque são o contrato da API — mudar
 * aqui quebraria o envio. O resto do código do frontend segue em inglês.
 */

export type Papel = 'admin' | 'usuario_pme';

export interface LoginRequest {
  email: string;
  senha: string;
}

export interface TokenPairResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface UserResponse {
  id_usuario: number;
  nome: string;
  email: string;
  papel: Papel;
  criado_em: string;
}
