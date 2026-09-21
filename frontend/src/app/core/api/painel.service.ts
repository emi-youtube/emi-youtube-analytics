import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { ResumoPainel } from './painel.models';

/**
 * Recurso "painel" (tela Início).
 *
 * Classe abstrata, e não interface, porque em TypeScript a interface some no
 * build e não serve de token de injeção. Quem depende disto injeta
 * `PainelService` e não sabe se está falando com a API ou com o mock — a troca
 * é um provider só, em `app.config.ts`.
 */
@Injectable()
export abstract class PainelService {
  abstract carregar(): Observable<ResumoPainel>;
}

/** Implementação real. Ativa quando `GET /api/v1/painel` existir. */
@Injectable()
export class PainelHttpService extends PainelService {
  private readonly http = inject(HttpClient);

  carregar(): Observable<ResumoPainel> {
    return this.http.get<ResumoPainel>(`${environment.apiBaseUrl}/painel`);
  }
}
