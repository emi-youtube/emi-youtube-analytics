import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { ResultadoDisponivel, ResultadoExecucao } from './resultados.models';

/** Recurso "resultado de execução" (tela Resultados). Ver `painel.service.ts`. */
@Injectable()
export abstract class ResultadosService {
  /** Execuções concluídas do usuário, da mais recente para a mais antiga. */
  abstract listarDisponiveis(): Observable<ResultadoDisponivel[]>;
  abstract carregar(idExecucao: number): Observable<ResultadoExecucao>;
}

@Injectable()
export class ResultadosHttpService extends ResultadosService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/execucoes`;

  listarDisponiveis(): Observable<ResultadoDisponivel[]> {
    return this.http.get<ResultadoDisponivel[]>(`${this.baseUrl}/resultados`);
  }

  carregar(idExecucao: number): Observable<ResultadoExecucao> {
    return this.http.get<ResultadoExecucao>(`${this.baseUrl}/${idExecucao}/resultado`);
  }
}
