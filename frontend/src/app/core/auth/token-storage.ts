import { Injectable, inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';

const REFRESH_TOKEN_KEY = 'emi.refresh_token';

/**
 * Guarda o refresh token.
 *
 * Só o refresh token é persistido; o access token vive em memória no
 * `AuthService`. Motivo: o access token viaja em todo request e expira em 15
 * min (`jwt_access_token_expire_minutes`), então mantê-lo fora do storage
 * reduz a janela de roubo por XSS. O refresh precisa sobreviver ao reload e é
 * revogável no servidor (`POST /auth/logout` apaga a linha em
 * `tokens_atualizacao`), então a troca é aceitável.
 *
 * Todo acesso é guardado por `isPlatformBrowser`: no SSR não existe
 * `localStorage` e ler direto derrubaria a renderização no servidor.
 */
@Injectable({ providedIn: 'root' })
export class TokenStorage {
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  read(): string | null {
    if (!this.isBrowser) {
      return null;
    }
    try {
      return localStorage.getItem(REFRESH_TOKEN_KEY);
    } catch {
      // Modo privado ou storage bloqueado: a sessão vira só-memória.
      return null;
    }
  }

  write(refreshToken: string): void {
    if (!this.isBrowser) {
      return;
    }
    try {
      localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    } catch {
      // Sem persistência a sessão acaba ao fechar a aba — não é erro fatal.
    }
  }

  clear(): void {
    if (!this.isBrowser) {
      return;
    }
    try {
      localStorage.removeItem(REFRESH_TOKEN_KEY);
    } catch {
      // Nada a fazer: já não há o que limpar.
    }
  }
}
