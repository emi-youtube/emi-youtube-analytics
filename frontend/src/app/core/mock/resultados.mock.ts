import { Injectable } from '@angular/core';
import { Observable, throwError } from 'rxjs';

import { HttpErrorResponse } from '@angular/common/http';
import { ResultadoDisponivel, ResultadoExecucao } from '../api/resultados.models';
import { ResultadosService } from '../api/resultados.service';
import { RESULTADOS_DEMO } from './dados-demo';
import { comLatencia } from './latencia';

/**
 * Substitui `GET /api/v1/execucoes/{id}/resultado` e a lista de resultados.
 *
 * Execução sem dados de demonstração devolve um `HttpErrorResponse` 404 de
 * verdade, e não um erro solto: a tela trata o 404 do mock pelo mesmo caminho
 * que vai tratar o da API.
 */
@Injectable()
export class ResultadosMockService extends ResultadosService {
  listarDisponiveis(): Observable<ResultadoDisponivel[]> {
    return comLatencia(() =>
      [...RESULTADOS_DEMO.values()]
        .map(resumir)
        .sort((a, b) => (b.concluido_em ?? '').localeCompare(a.concluido_em ?? '')),
    );
  }

  carregar(idExecucao: number): Observable<ResultadoExecucao> {
    const resultado = RESULTADOS_DEMO.get(idExecucao);
    if (!resultado) {
      return throwError(
        () =>
          new HttpErrorResponse({
            status: 404,
            statusText: 'Not Found',
            error: { detail: 'Esta execução não faz parte dos dados de demonstração.' },
          }),
      );
    }
    return comLatencia(() => resultado);
  }
}

function resumir(resultado: ResultadoExecucao): ResultadoDisponivel {
  return {
    id_execucao: resultado.id_execucao,
    id_modelo: resultado.id_modelo,
    nome_modelo_analise: resultado.nome_modelo_analise,
    concluido_em: resultado.concluido_em,
    distribuicao: resultado.distribuicao,
    total_videos: resultado.videos.length,
    total_temas: resultado.temas.length,
  };
}
