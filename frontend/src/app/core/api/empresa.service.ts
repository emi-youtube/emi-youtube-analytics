import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { Convite, ConviteCreate, ConviteCriado, Membro } from './empresa.models';

/**
 * Cliente de `/api/v1/empresa` (ADR-011): membros e convites.
 *
 * Sem estado, como os outros serviços: quem guarda as listas é o componente.
 * As rotas de convite e de remoção respondem 403 para quem não é dono.
 */
@Injectable({ providedIn: 'root' })
export class EmpresaService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/empresa`;

  membros(): Observable<Membro[]> {
    return this.http.get<Membro[]>(`${this.baseUrl}/membros`);
  }

  removerMembro(idUsuario: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/membros/${idUsuario}`);
  }

  convites(): Observable<Convite[]> {
    return this.http.get<Convite[]>(`${this.baseUrl}/convites`);
  }

  convidar(dados: ConviteCreate): Observable<ConviteCriado> {
    return this.http.post<ConviteCriado>(`${this.baseUrl}/convites`, dados);
  }

  revogarConvite(idConvite: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/convites/${idConvite}`);
  }
}
