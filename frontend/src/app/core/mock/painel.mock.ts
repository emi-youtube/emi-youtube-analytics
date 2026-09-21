import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { PainelService } from '../api/painel.service';
import { ResumoPainel } from '../api/painel.models';
import { RESULTADOS_DEMO, VERSAO_MODELO } from './dados-demo';
import { comLatencia } from './latencia';

/** Substitui `GET /api/v1/painel` enquanto o endpoint não existe. */
@Injectable()
export class PainelMockService extends PainelService {
  carregar(): Observable<ResumoPainel> {
    return comLatencia(() => montar());
  }
}

function montar(): ResumoPainel {
  const joalheria = RESULTADOS_DEMO.get(12)!;
  const blackFriday = RESULTADOS_DEMO.get(8)!;

  return {
    destaque: {
      id_execucao: joalheria.id_execucao,
      nome_modelo_analise: joalheria.nome_modelo_analise,
      concluido_em: joalheria.concluido_em,
      total_comentarios: joalheria.distribuicao.total,
      total_videos: joalheria.videos.length,
      total_temas: joalheria.temas.length,
      distribuicao: joalheria.distribuicao,
    },
    modelos: [
      {
        id_modelo: 1,
        nome: 'Campanha Verão — linha esportiva',
        total_videos: 4,
        status_ultima_execucao: 'processando',
        ultima_execucao_em: '2026-09-21T17:32:00Z',
        motivo_da_falha: null,
        id_execucao_concluida: null,
      },
      {
        id_modelo: joalheria.id_modelo,
        nome: joalheria.nome_modelo_analise,
        total_videos: joalheria.videos.length,
        status_ultima_execucao: 'concluida',
        ultima_execucao_em: joalheria.concluido_em,
        motivo_da_falha: null,
        id_execucao_concluida: joalheria.id_execucao,
      },
      {
        id_modelo: blackFriday.id_modelo,
        nome: blackFriday.nome_modelo_analise,
        total_videos: blackFriday.videos.length,
        status_ultima_execucao: 'concluida',
        ultima_execucao_em: blackFriday.concluido_em,
        motivo_da_falha: null,
        id_execucao_concluida: blackFriday.id_execucao,
      },
      {
        id_modelo: 5,
        nome: 'Institucional — fintech regional',
        total_videos: 3,
        status_ultima_execucao: 'erro',
        ultima_execucao_em: '2026-09-20T11:02:00Z',
        motivo_da_falha: 'Cota diária da YouTube API esgotada',
        id_execucao_concluida: null,
      },
    ],
    totais: {
      comentarios_analisados: 28_417,
      execucoes_concluidas: 12,
      videos_acompanhados: 31,
    },
    cota_youtube: {
      unidades_usadas: 3_400,
      unidades_limite: 10_000,
      renova_em: proximaMeiaNoite(),
    },
    versao_modelo: VERSAO_MODELO,
  };
}

/** A cota da YouTube API zera à meia-noite; aqui basta ser sempre "hoje à 0h". */
function proximaMeiaNoite(): string {
  const amanha = new Date();
  amanha.setHours(24, 0, 0, 0);
  return amanha.toISOString();
}
