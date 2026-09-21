import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { FiltroComentarios, PaginaComentarios } from '../api/comentarios.models';
import { ComentariosService } from '../api/comentarios.service';
import { DistribuicaoSentimento } from '../api/dominio.models';
import { ComentarioAnalisado } from '../api/resultados.models';
import { COMENTARIOS_DEMO } from './dados-demo';
import { comLatencia } from './latencia';

/**
 * Substitui `GET /api/v1/execucoes/{id}/comentarios`.
 *
 * Filtra e pagina de verdade sobre a amostra de demonstração — se filtrasse
 * "de mentira", a tela passaria na revisão com um bug de paginação que só
 * apareceria depois de ligar a API.
 */
@Injectable()
export class ComentariosMockService extends ComentariosService {
  listar(idExecucao: number, filtro: FiltroComentarios): Observable<PaginaComentarios> {
    return comLatencia(() => paginar(COMENTARIOS_DEMO.get(idExecucao) ?? [], filtro));
  }
}

/** Tudo menos o sentimento: os chips de sentimento mostram a contagem entre si. */
function casaComFiltroBase(item: ComentarioAnalisado, filtro: FiltroComentarios): boolean {
  if (filtro.id_tema !== undefined && !item.temas.some((t) => t.id_tema === filtro.id_tema)) {
    return false;
  }
  if (filtro.id_video !== undefined && item.video.id_video !== filtro.id_video) {
    return false;
  }
  const busca = filtro.busca?.trim().toLowerCase();
  if (busca && !item.comentario.texto.toLowerCase().includes(busca)) {
    return false;
  }
  return true;
}

function contar(itens: ComentarioAnalisado[]): DistribuicaoSentimento {
  const contagem = { positivo: 0, neutro: 0, negativo: 0, total: itens.length };
  for (const item of itens) {
    contagem[item.analise.sentimento] += 1;
  }
  return contagem;
}

function paginar(todos: ComentarioAnalisado[], filtro: FiltroComentarios): PaginaComentarios {
  const base = todos.filter((item) => casaComFiltroBase(item, filtro));
  const filtrados =
    filtro.sentimento === undefined
      ? base
      : base.filter((item) => item.analise.sentimento === filtro.sentimento);

  const inicio = (filtro.pagina - 1) * filtro.tamanho;

  return {
    itens: filtrados.slice(inicio, inicio + filtro.tamanho),
    total: filtrados.length,
    pagina: filtro.pagina,
    tamanho: filtro.tamanho,
    contagem_por_sentimento: contar(base),
  };
}
