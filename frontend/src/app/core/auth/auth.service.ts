import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import {
  Observable,
  catchError,
  finalize,
  map,
  of,
  shareReplay,
  switchMap,
  tap,
  throwError,
} from 'rxjs';

import { environment } from '../../../environments/environment';
import { skipAuth } from './auth.context';
import {
  ConviteParaCadastro,
  LoginRequest,
  MensagemResponse,
  RegisterRequest,
  TokenPairResponse,
  TrocarSenhaRequest,
  UserResponse,
} from './auth.models';
import { TokenStorage } from './token-storage';

/**
 * Estado da sessão (UC01).
 *
 * O access token mora só aqui, em memória. Depois de um reload ele não existe
 * mais, e a sessão é reconstruída a partir do refresh token persistido —
 * é o que `ensureSession()` faz, chamado pelo `authGuard`.
 */
/**
 * A conta foi criada, mas o login automático logo depois falhou.
 *
 * Precisa ser distinguível de uma falha do cadastro em si: o usuário já tem
 * conta e não deve tentar de novo — na segunda tentativa tomaria 409.
 */
export class ContaCriadaSemSessao extends Error {
  constructor(readonly causa: unknown) {
    super('Conta criada, mas o login automático falhou.');
    this.name = 'ContaCriadaSemSessao';
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly storage = inject(TokenStorage);
  private readonly baseUrl = `${environment.apiBaseUrl}/auth`;

  private readonly accessToken = signal<string | null>(null);
  private readonly currentUser = signal<UserResponse | null>(null);

  /** Um refresh de cada vez: várias requisições que tomam 401 juntas esperam o mesmo. */
  private refreshInFlight: Observable<string> | null = null;
  private restoreInFlight: Observable<boolean> | null = null;

  readonly usuario = this.currentUser.asReadonly();
  readonly isAuthenticated = computed(() => this.accessToken() !== null);

  /** Lido pelo interceptor a cada requisição. */
  token(): string | null {
    return this.accessToken();
  }

  hasPersistedSession(): boolean {
    return this.storage.read() !== null;
  }

  /**
   * Empresa nova (ADR-014): só PEDE o cadastro. O backend responde 202 igual
   * tenha o e-mail conta ou não e manda um link; a conta nasce quando a pessoa
   * abre o link (`confirmarCadastro`).
   */
  pedirCadastro(dados: RegisterRequest): Observable<MensagemResponse> {
    return this.http.post<MensagemResponse>(`${this.baseUrl}/registrar`, dados, {
      context: skipAuth(),
    });
  }

  /**
   * Link do e-mail de confirmação (`/confirmar-cadastro?token=...`): cria a
   * empresa e a conta de dono e já devolve a sessão.
   */
  confirmarCadastro(token: string): Observable<UserResponse> {
    return this.http
      .post<TokenPairResponse>(
        `${this.baseUrl}/confirmar-cadastro`,
        { token },
        { context: skipAuth() },
      )
      .pipe(
        tap((tokens) => this.guardarTokens(tokens)),
        switchMap(() => this.loadCurrentUser()),
      );
  }

  /**
   * UC02 por convite — cria a conta e já entra com ela.
   *
   * Por convite não há confirmação: o link do convite já chegou por e-mail.
   * `POST /auth/registrar` devolve o usuário, não tokens; a sessão vem do
   * login encadeado. Se esse login falhar, o erro sai como
   * `ContaCriadaSemSessao` para a tela não dizer que o cadastro deu errado —
   * a conta existe.
   */
  registrarPorConvite(dados: RegisterRequest): Observable<UserResponse> {
    return this.http
      .post<UserResponse>(`${this.baseUrl}/registrar`, dados, { context: skipAuth() })
      .pipe(
        switchMap(() =>
          this.login({ email: dados.email, senha: dados.senha }).pipe(
            catchError((erro: unknown) => throwError(() => new ContaCriadaSemSessao(erro))),
          ),
        ),
      );
  }

  login(credenciais: LoginRequest): Observable<UserResponse> {
    return this.http
      .post<TokenPairResponse>(`${this.baseUrl}/login`, credenciais, { context: skipAuth() })
      .pipe(
        tap((tokens) => this.guardarTokens(tokens)),
        switchMap(() => this.loadCurrentUser()),
      );
  }

  private guardarTokens(tokens: TokenPairResponse): void {
    this.accessToken.set(tokens.access_token);
    this.storage.write(tokens.refresh_token);
  }

  /** Dados do convite do link `/entrar?convite=...`: e-mail travado e empresa. */
  consultarConvite(token: string): Observable<ConviteParaCadastro> {
    return this.http.post<ConviteParaCadastro>(
      `${this.baseUrl}/convites/consultar`,
      { token },
      { context: skipAuth() },
    );
  }

  /**
   * Troca a senha de quem está logado.
   *
   * O backend revoga TODOS os refresh tokens e devolve um par novo para esta
   * sessão — guardá-lo é o que impede a própria aba de cair no próximo refresh.
   */
  trocarSenha(dados: TrocarSenhaRequest): Observable<void> {
    return this.http.post<TokenPairResponse>(`${this.baseUrl}/trocar-senha`, dados).pipe(
      tap((tokens) => this.guardarTokens(tokens)),
      map(() => void 0),
    );
  }

  /**
   * Aceite da versão vigente dos termos por quem já tem conta (ADR-012). Fecha o
   * modal do `Shell` sem recarregar o usuário: a resposta é 204.
   */
  aceitarTermos(): Observable<void> {
    return this.http
      .post<void>(`${environment.apiBaseUrl}/conta/aceitar-termos`, {})
      .pipe(tap(() => this.currentUser.update((u) => (u ? { ...u, termos_pendentes: false } : u))));
  }

  /** Sempre 202 com a mesma mensagem, exista ou não a conta. */
  esqueciSenha(email: string): Observable<MensagemResponse> {
    return this.http.post<MensagemResponse>(
      `${this.baseUrl}/esqueci-senha`,
      { email },
      { context: skipAuth() },
    );
  }

  redefinirSenha(token: string, novaSenha: string): Observable<void> {
    return this.http.post<void>(
      `${this.baseUrl}/redefinir-senha`,
      { token, nova_senha: novaSenha },
      { context: skipAuth() },
    );
  }

  /**
   * Revoga o refresh token no servidor e zera o estado local.
   *
   * A limpeza local acontece mesmo se a chamada falhar: o usuário pediu para
   * sair, e deixar a sessão de pé na aba por causa de rede seria pior do que
   * um refresh token que sobrevive até expirar no banco.
   */
  logout(): Observable<void> {
    const refreshToken = this.storage.read();
    this.clearSession();

    if (!refreshToken) {
      return of(void 0);
    }

    return this.http
      .post<void>(
        `${this.baseUrl}/logout`,
        { refresh_token: refreshToken },
        { context: skipAuth() },
      )
      .pipe(catchError(() => of(void 0)));
  }

  /**
   * Troca o refresh token por um par novo (rotação).
   *
   * Chamado pelo interceptor no 401. Enquanto uma troca está em voo, as demais
   * assinam o mesmo Observable (`shareReplay`). Com rotação isso deixou de ser
   * só economia: o refresh antigo morre no primeiro uso, e um segundo refresh
   * paralelo com ele seria lido pelo backend como REUSO — que derruba todas as
   * sessões da conta.
   */
  refreshAccessToken(): Observable<string> {
    if (this.refreshInFlight) {
      return this.refreshInFlight;
    }

    const refreshToken = this.storage.read();
    if (!refreshToken) {
      return throwError(() => new Error('Sessão sem refresh token.'));
    }

    this.refreshInFlight = this.http
      .post<TokenPairResponse>(
        `${this.baseUrl}/refresh`,
        { refresh_token: refreshToken },
        { context: skipAuth() },
      )
      .pipe(
        tap((tokens) => this.guardarTokens(tokens)),
        map((tokens) => tokens.access_token),
        catchError((erro) => {
          // Refresh recusado: o token expirou ou foi revogado. Não há volta.
          this.clearSession();
          return throwError(() => erro);
        }),
        finalize(() => {
          this.refreshInFlight = null;
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );

    return this.refreshInFlight;
  }

  /**
   * Garante uma sessão utilizável antes de entrar numa rota protegida.
   *
   * Depois de um F5 o access token sumiu, mas o refresh continua no storage —
   * aqui ele vira sessão de novo, sem mandar o usuário para o login à toa.
   */
  ensureSession(): Observable<boolean> {
    if (this.isAuthenticated()) {
      return of(true);
    }
    if (this.restoreInFlight) {
      return this.restoreInFlight;
    }
    if (!this.hasPersistedSession()) {
      return of(false);
    }

    this.restoreInFlight = this.refreshAccessToken().pipe(
      switchMap(() => this.loadCurrentUser()),
      map(() => true),
      catchError(() => {
        this.clearSession();
        return of(false);
      }),
      finalize(() => {
        this.restoreInFlight = null;
      }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );

    return this.restoreInFlight;
  }

  /** `GET /auth/eu` — quem é o dono do token e de qual empresa. Alimenta a nav. */
  loadCurrentUser(): Observable<UserResponse> {
    return this.http
      .get<UserResponse>(`${this.baseUrl}/eu`)
      .pipe(tap((usuario) => this.currentUser.set(usuario)));
  }

  clearSession(): void {
    this.accessToken.set(null);
    this.currentUser.set(null);
    this.storage.clear();
  }
}
