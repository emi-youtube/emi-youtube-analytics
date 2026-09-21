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
import { AccessTokenResponse, LoginRequest, TokenPairResponse, UserResponse } from './auth.models';
import { TokenStorage } from './token-storage';

/**
 * Estado da sessão (UC01).
 *
 * O access token mora só aqui, em memória. Depois de um reload ele não existe
 * mais, e a sessão é reconstruída a partir do refresh token persistido —
 * é o que `ensureSession()` faz, chamado pelo `authGuard`.
 */
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

  login(credenciais: LoginRequest): Observable<UserResponse> {
    return this.http
      .post<TokenPairResponse>(`${this.baseUrl}/login`, credenciais, { context: skipAuth() })
      .pipe(
        tap((tokens) => {
          this.accessToken.set(tokens.access_token);
          this.storage.write(tokens.refresh_token);
        }),
        switchMap(() => this.loadCurrentUser()),
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
   * Troca o refresh token por um access token novo.
   *
   * Chamado pelo interceptor no 401. Enquanto uma troca está em voo, as demais
   * assinam o mesmo Observable (`shareReplay`) — senão N requisições paralelas
   * dispararicam N refreshes.
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
      .post<AccessTokenResponse>(
        `${this.baseUrl}/refresh`,
        { refresh_token: refreshToken },
        { context: skipAuth() },
      )
      .pipe(
        map((resposta) => resposta.access_token),
        tap((token) => this.accessToken.set(token)),
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

  /** `GET /auth/eu` — quem é o dono do token. Alimenta o rodapé da nav. */
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
