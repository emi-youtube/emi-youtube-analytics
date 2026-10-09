import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { CotaAdmin } from './admin.models';

/**
 * Cliente de `/api/v1/admin` — só o papel global `admin`; os outros recebem 403.
 * Sem estado, como os outros serviços.
 */
@Injectable({ providedIn: 'root' })
export class AdminService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/admin`;

  cotaYoutube(dias = 30): Observable<CotaAdmin> {
    const params = new HttpParams().set('dias', dias);
    return this.http.get<CotaAdmin>(`${this.baseUrl}/cota-youtube`, { params });
  }
}
