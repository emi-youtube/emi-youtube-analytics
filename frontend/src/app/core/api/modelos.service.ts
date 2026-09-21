import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { ModeloAnalise, ModeloAnaliseCreate, ModeloAnaliseUpdate } from './modelos.models';

/**
 * Cliente de `/api/v1/modelos-analise` (UC02).
 *
 * Sem cache nem estado: o serviço só traduz chamada HTTP. Quem guarda a lista
 * na tela é o componente, em signals — dois donos do mesmo estado é o caminho
 * mais curto para a tela mostrar algo que o servidor já não tem.
 */
@Injectable({ providedIn: 'root' })
export class ModelosService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/modelos-analise`;

  listar(): Observable<ModeloAnalise[]> {
    return this.http.get<ModeloAnalise[]>(this.baseUrl);
  }

  detalhar(idModelo: number): Observable<ModeloAnalise> {
    return this.http.get<ModeloAnalise>(`${this.baseUrl}/${idModelo}`);
  }

  criar(dados: ModeloAnaliseCreate): Observable<ModeloAnalise> {
    return this.http.post<ModeloAnalise>(this.baseUrl, dados);
  }

  atualizar(idModelo: number, dados: ModeloAnaliseUpdate): Observable<ModeloAnalise> {
    return this.http.patch<ModeloAnalise>(`${this.baseUrl}/${idModelo}`, dados);
  }

  /** 204 em caso de sucesso; 409 quando o modelo já tem execuções. */
  remover(idModelo: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${idModelo}`);
  }
}
