import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { Execucao } from './execucoes.models';

/** Cliente de `/api/v1/execucoes` (UC03 dispara, UC04 acompanha). */
@Injectable({ providedIn: 'root' })
export class ExecucoesService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/execucoes`;

  listar(): Observable<Execucao[]> {
    return this.http.get<Execucao[]>(this.baseUrl);
  }

  /**
   * Responde 202: a execução foi aceita e enfileirada, não executada.
   *
   * O corpo já vem com a execução em `pendente` — é ela que a tela mostra na
   * hora, sem esperar worker nenhum.
   */
  disparar(idModelo: number): Observable<Execucao> {
    return this.http.post<Execucao>(this.baseUrl, { id_modelo: idModelo });
  }

  /** Fonte do polling do UC04. */
  detalhar(idExecucao: number): Observable<Execucao> {
    return this.http.get<Execucao>(`${this.baseUrl}/${idExecucao}`);
  }
}
