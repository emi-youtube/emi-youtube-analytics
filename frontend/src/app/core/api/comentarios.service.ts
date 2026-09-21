import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { FiltroComentarios, PaginaComentarios } from './comentarios.models';
import { environment } from '../../../environments/environment';

/** Recurso "comentários de uma execução". Ver `painel.service.ts`. */
@Injectable()
export abstract class ComentariosService {
  abstract listar(idExecucao: number, filtro: FiltroComentarios): Observable<PaginaComentarios>;
}

@Injectable()
export class ComentariosHttpService extends ComentariosService {
  private readonly http = inject(HttpClient);

  listar(idExecucao: number, filtro: FiltroComentarios): Observable<PaginaComentarios> {
    return this.http.get<PaginaComentarios>(
      `${environment.apiBaseUrl}/execucoes/${idExecucao}/comentarios`,
      { params: montarParams(filtro) },
    );
  }
}

/** Filtro vazio não vira `?busca=` na URL — o backend receberia string vazia. */
function montarParams(filtro: FiltroComentarios): HttpParams {
  let params = new HttpParams().set('pagina', filtro.pagina).set('tamanho', filtro.tamanho);

  if (filtro.busca?.trim()) {
    params = params.set('busca', filtro.busca.trim());
  }
  if (filtro.id_tema !== undefined) {
    params = params.set('id_tema', filtro.id_tema);
  }
  if (filtro.id_video !== undefined) {
    params = params.set('id_video', filtro.id_video);
  }
  if (filtro.sentimento !== undefined) {
    params = params.set('sentimento', filtro.sentimento);
  }

  return params;
}
