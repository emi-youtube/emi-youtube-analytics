import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, switchMap, tap } from 'rxjs';

import { environment } from '../../../environments/environment';
import { semRenovar } from '../auth/auth.context';
import { AuthService } from '../auth/auth.service';
import { MeusDados } from './conta.models';

/** Direitos do titular sobre a própria conta: exportar e excluir (ADR-012). */
@Injectable({ providedIn: 'root' })
export class ContaService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  private readonly baseUrl = `${environment.apiBaseUrl}/conta`;

  meusDados(): Observable<MeusDados> {
    return this.http.get<MeusDados>(`${this.baseUrl}/meus-dados`);
  }

  /**
   * `DELETE /conta` com a senha no corpo.
   *
   * Aqui o 401 é "senha incorreta", não sessão vencida: o pedido vai com
   * `semRenovar()`, e para isso renova ANTES — com o access token fresco, um 401
   * só pode ser a senha. Deu certo, a sessão local é encerrada: a conta não existe
   * mais.
   */
  excluir(senha: string): Observable<void> {
    return this.auth.refreshAccessToken().pipe(
      switchMap(() =>
        this.http.delete<void>(this.baseUrl, { body: { senha }, context: semRenovar() }),
      ),
      tap(() => this.auth.clearSession()),
    );
  }
}
