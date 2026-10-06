/**
 * Espelha os schemas de `backend/app/schemas/auth.py`.
 *
 * Os nomes de campo ficam em português porque são o contrato da API — mudar
 * aqui quebraria o envio. O resto do código do frontend segue em inglês.
 */

export type Papel = 'admin' | 'usuario_pme';

/** Papel DENTRO da empresa (ADR-011). Independe do `Papel` global. */
export type PapelEmpresa = 'dono' | 'membro';

export interface LoginRequest {
  email: string;
  senha: string;
}

/**
 * Corpo de `POST /auth/registrar`.
 *
 * Exatamente um de `nome_empresa` (cria a empresa, entra como dono) ou
 * `token_convite` (entra na empresa do convite). Não tem `papel`: o backend
 * sempre grava `usuario_pme`.
 */
export interface RegisterRequest {
  nome: string;
  email: string;
  senha: string;
  nome_empresa?: string;
  token_convite?: string;
  /** Obrigatório e verdadeiro (ADR-012): o backend responde 422 sem ele. */
  aceite_termos: true;
}

/** `POST /auth/refresh` também devolve um par: o refresh é rotacionado a cada uso. */
export interface TokenPairResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface EmpresaResumo {
  id_empresa: number;
  nome: string;
}

export interface UserResponse {
  id_usuario: number;
  nome: string;
  email: string;
  papel: Papel;
  papel_empresa: PapelEmpresa;
  empresa: EmpresaResumo;
  criado_em: string;
  /**
   * Só `GET /auth/eu` traz: falta aceitar a versão vigente dos termos. Verdadeiro
   * abre o modal bloqueante do `Shell`.
   */
  termos_pendentes?: boolean;
}

/** `POST /auth/convites/consultar` — para o cadastro travar o e-mail do convite. */
export interface ConviteParaCadastro {
  email: string;
  nome_empresa: string;
  papel_empresa: PapelEmpresa;
}

export interface TrocarSenhaRequest {
  senha_atual: string;
  nova_senha: string;
}

export interface MensagemResponse {
  detail: string;
}
