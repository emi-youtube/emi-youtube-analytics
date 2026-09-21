import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  FiltroComentarios,
  PaginaComentarios,
  TAMANHO_PAGINA_PADRAO,
} from '../api/comentarios.models';
import { ComentariosService } from '../api/comentarios.service';
import { percentuais } from '../api/dominio.models';
import { ResultadosService } from '../api/resultados.service';
import { RESULTADOS_DEMO } from './dados-demo';
import { comLatencia } from './latencia';
import { provideDadosDeDemonstracao } from './mock.providers';

const JOALHERIA = 12;
/** Tema "Preço" da execução 12 (segundo tema da semente). */
const TEMA_PRECO = 1202;

describe('latência simulada', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('não responde no mesmo tick — é o que faz o estado de carregamento aparecer', () => {
    const recebido = vi.fn();
    comLatencia(() => 'pronto').subscribe(recebido);

    expect(recebido).not.toHaveBeenCalled();

    // Abaixo do piso da faixa (300 ms) nada pode ter chegado.
    vi.advanceTimersByTime(299);
    expect(recebido).not.toHaveBeenCalled();

    // Acima do teto (800 ms) já tem que ter chegado, qualquer que seja o sorteio.
    vi.advanceTimersByTime(501);
    expect(recebido).toHaveBeenCalledWith('pronto');
  });
});

describe('ResultadosMockService', () => {
  let api: ResultadosService;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({ providers: [provideDadosDeDemonstracao()] });
    api = TestBed.inject(ResultadosService);
  });

  afterEach(() => vi.useRealTimers());

  it('devolve 404 de verdade para execução sem demonstração', () => {
    const erro = vi.fn();
    api.carregar(999).subscribe({ error: erro });
    vi.advanceTimersByTime(1000);

    expect(erro).toHaveBeenCalled();
    const recebido = erro.mock.calls[0][0] as HttpErrorResponse;
    expect(recebido).toBeInstanceOf(HttpErrorResponse);
    expect(recebido.status).toBe(404);
  });
});

describe('conjunto de demonstração', () => {
  it('a distribuição geral é a soma dos vídeos', () => {
    for (const resultado of RESULTADOS_DEMO.values()) {
      const somaDosVideos = resultado.videos.reduce(
        (total, { distribuicao }) => total + distribuicao.total,
        0,
      );
      expect(resultado.distribuicao.total).toBe(somaDosVideos);
      expect(
        resultado.distribuicao.positivo +
          resultado.distribuicao.neutro +
          resultado.distribuicao.negativo,
      ).toBe(resultado.distribuicao.total);
    }
  });

  it('os percentuais sempre fecham em 100', () => {
    for (const resultado of RESULTADOS_DEMO.values()) {
      for (const { distribuicao } of [...resultado.videos, ...resultado.temas]) {
        const p = percentuais(distribuicao);
        expect(p.positivo + p.neutro + p.negativo).toBe(100);
      }
    }
  });

  it('nenhum comentário de demonstração vaza identidade do autor', () => {
    for (const resultado of RESULTADOS_DEMO.values()) {
      for (const item of resultado.comentarios_representativos) {
        // autor_hash existe (é coluna), mas tem que ser opaco: 64 hex, nada mais.
        expect(item.comentario.autor_hash).toMatch(/^[0-9a-f]{64}$/);
      }
    }
  });
});

describe('ComentariosMockService', () => {
  let api: ComentariosService;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({ providers: [provideDadosDeDemonstracao()] });
    api = TestBed.inject(ComentariosService);
  });

  afterEach(() => vi.useRealTimers());

  /** Resolve o Observable adiantando os timers da latência simulada. */
  function listar(filtro: FiltroComentarios): PaginaComentarios {
    const recebido = vi.fn();
    api.listar(JOALHERIA, filtro).subscribe(recebido);
    vi.advanceTimersByTime(1000);
    expect(recebido).toHaveBeenCalled();
    return recebido.mock.calls[0][0] as PaginaComentarios;
  }

  it('pagina de verdade, sem repetir item entre as páginas', () => {
    const primeira = listar({ pagina: 1, tamanho: TAMANHO_PAGINA_PADRAO });
    const segunda = listar({ pagina: 2, tamanho: TAMANHO_PAGINA_PADRAO });

    expect(primeira.itens).toHaveLength(TAMANHO_PAGINA_PADRAO);
    const idsPrimeira = primeira.itens.map((i) => i.comentario.id_comentario);
    const idsSegunda = segunda.itens.map((i) => i.comentario.id_comentario);
    expect(idsPrimeira.some((id) => idsSegunda.includes(id))).toBe(false);
    expect(primeira.total).toBe(segunda.total);
  });

  it('filtra por tema usando COMENTARIO_TEMA, não só o tema principal', () => {
    const pagina = listar({ pagina: 1, tamanho: 50, id_tema: TEMA_PRECO });

    expect(pagina.total).toBeGreaterThan(0);
    for (const item of pagina.itens) {
      expect(item.temas.some((t) => t.id_tema === TEMA_PRECO)).toBe(true);
    }
  });

  it('busca no texto do comentário', () => {
    const pagina = listar({ pagina: 1, tamanho: 50, busca: 'parcela' });

    expect(pagina.total).toBeGreaterThan(0);
    for (const item of pagina.itens) {
      expect(item.comentario.texto.toLowerCase()).toContain('parcela');
    }
  });

  it('a contagem dos chips ignora o filtro de sentimento', () => {
    const todos = listar({ pagina: 1, tamanho: 50, id_tema: TEMA_PRECO });
    const negativos = listar({
      pagina: 1,
      tamanho: 50,
      id_tema: TEMA_PRECO,
      sentimento: 'negativo',
    });

    // Os chips continuam mostrando os três números depois de escolher um deles.
    expect(negativos.contagem_por_sentimento).toEqual(todos.contagem_por_sentimento);
    // Já o total da lista acompanha o filtro.
    expect(negativos.total).toBe(todos.contagem_por_sentimento.negativo);
  });
});
