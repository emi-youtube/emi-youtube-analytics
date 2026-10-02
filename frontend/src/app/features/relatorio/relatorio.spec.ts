import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { PLATFORM_ID } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Title } from '@angular/platform-browser';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { ResultadoExecucao } from '../../core/api/resultados.models';
import { ResultadosHttpService, ResultadosService } from '../../core/api/resultados.service';
import { Relatorio } from './relatorio';

const URL_RESULTADO = `${environment.apiBaseUrl}/execucoes/12/resultado`;

/** Resposta realista de `GET /execucoes/12/resultado`, com sobrescritas. */
function resultado(sobrescritas: Partial<ResultadoExecucao> = {}): ResultadoExecucao {
  const comentario = {
    comentario: {
      id_comentario: 501,
      id_video: 1,
      youtube_comment_id: 'Ugx1',
      autor_hash: 'f'.repeat(64),
      texto: 'Achei o preço alto demais para o que o produto entrega.',
      publicado_em: '2026-09-20T10:00:00Z',
    },
    analise: {
      id_analise: 900,
      id_comentario: 501,
      id_versao_modelo: 1,
      sentimento: 'negativo' as const,
      tema: null,
      justificativa: null,
      processado_em: '2026-09-21T13:13:00Z',
      confianca: null,
    },
    video: { id_video: 1, youtube_video_id: 'dQw4w9WgXcQ', titulo: 'Campanha Verão' },
    temas: [],
  };

  return {
    id_execucao: 12,
    id_modelo: 3,
    nome_modelo_analise: 'Campanha Verão',
    concluido_em: '2026-09-21T13:13:00Z',
    distribuicao: { positivo: 200, neutro: 100, negativo: 100, total: 400 },
    alcance: {
      visualizacoes: 50_000,
      curtidas: 900,
      comentarios: 400,
      comentarios_por_mil_views: 8,
    },
    recorte: {
      registrado: true,
      coletado_em: '2026-09-21T13:12:00Z',
      termo_pesquisa: 'tênis',
      publicado_apos: '2026-09-01',
      limite_informado: 400,
      limite_aplicado: 400,
      comentarios_lidos: 1_250,
      comentarios_coletados: 400,
      descartados_por_data: 10,
      descartados_por_termo: 840,
      limite_atingido: true,
    },
    videos: [
      {
        video: {
          id_video: 1,
          id_execucao: 12,
          youtube_video_id: 'dQw4w9WgXcQ',
          titulo: 'Campanha Verão — filme 30s',
          canal: 'Marca X',
          publicado_em: '2026-08-30T12:00:00Z',
          visualizacoes: 50_000,
          curtidas: 900,
        },
        distribuicao: { positivo: 200, neutro: 100, negativo: 100, total: 400 },
      },
    ],
    temas: [
      {
        tema: {
          id_tema: 7,
          id_execucao: 12,
          rotulo_tema: 'Preço',
          palavras_chave: ['preço', 'caro', 'valor'],
        },
        distribuicao: { positivo: 10, neutro: 20, negativo: 30, total: 60 },
        comentario_representativo: comentario,
      },
    ],
    comentarios_representativos: [],
    insights: [
      {
        tipo: 'tema_mais_criticado',
        valores: { rotulo_tema: 'Preço' },
        amostra: { tamanho: 60, minimo_exigido: 30 },
        origem: { id_execucoes: [12], id_tema: 7 },
        texto: 'O tema “Preço” é o que mais concentra críticas.',
      },
    ],
    insights_da_campanha: [
      {
        tipo: 'variacao_de_sentimento',
        valores: {},
        amostra: { tamanho: 400, minimo_exigido: 100 },
        origem: { id_execucoes: [9, 12] },
        texto: 'A proporção de negativos subiu desde a coleta anterior.',
      },
    ],
    ponto_de_atencao: null,
    versao_modelo: {
      id_versao: 1,
      nome_modelo: 'lexico-sentilex',
      versao: '1.0.0',
      metricas_avaliacao: null,
      status: 'ativo',
    },
    ...sobrescritas,
  };
}

describe('Relatorio', () => {
  let fixture: ComponentFixture<Relatorio>;
  let httpMock: HttpTestingController;

  function montar(plataforma: 'browser' | 'server' = 'browser'): void {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ResultadosService, useClass: ResultadosHttpService },
        { provide: PLATFORM_ID, useValue: plataforma },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ id: '12' }) } },
        },
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Relatorio);
  }

  function responder(corpo: ResultadoExecucao): HTMLElement {
    httpMock.expectOne(URL_RESULTADO).flush(corpo);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  /**
   * Texto como o leitor vê: o Angular tira o espaço entre tags, e o
   * `textContent` colaria "Positivo" em "200". Separa elemento de elemento.
   */
  function texto(el: Element | null): string {
    if (!el) {
      return '';
    }
    return [...el.childNodes]
      .map((no) =>
        no.nodeType === Node.ELEMENT_NODE
          ? texto(no as Element)
          : no.nodeType === Node.TEXT_NODE
            ? (no.textContent ?? '')
            : '',
      )
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  afterEach(() => {
    httpMock.verify();
    vi.restoreAllMocks();
  });

  it('monta as sete partes na ordem pedida', () => {
    montar();
    const el = responder(resultado());

    const titulos = [...el.querySelectorAll('h2')].map((h) => texto(h));
    expect(titulos).toEqual([
      '1. Identificação',
      '2. Sentimento geral',
      '3. Resultado por vídeo',
      '4. Temas',
      '5. Insights',
      '6. Como ler este relatório',
    ]);
    // 7: o rodapé vem depois de todas as seções.
    expect(el.querySelector('article > footer.rodape')).not.toBeNull();
    expect(el.querySelector('article')?.lastElementChild?.classList).toContain('rodape');
  });

  it('identifica campanha, execução e o recorte que valeu', () => {
    montar();
    const ficha = texto(responder(resultado()).querySelector('#sec-identificacao')!.parentElement);

    expect(ficha).toContain('Campanha Verão');
    expect(ficha).toContain('nº 12');
    expect(ficha).toContain('Vídeos 1 (dQw4w9WgXcQ)');
    expect(ficha).toContain('contendo “tênis”');
    expect(ficha).toContain('01/09/2026');
    expect(ficha).toContain('400 — atingido');
    expect(ficha).toContain('400 coletados de 1.250 lidos');
    expect(ficha).toContain('O limite interrompeu a coleta');
  });

  it('não chama de "hoje" a data da coleta: o PDF é lido depois', () => {
    montar();
    const ficha = texto(responder(resultado()).querySelector('.ficha'));

    expect(ficha).not.toMatch(/hoje|ontem/);
    expect(ficha).toMatch(/Data da coleta \d{2}\/\d{2}\/2026 às \d{2}:\d{2}/);
  });

  it('traz contagens e percentuais do sentimento geral', () => {
    montar();
    const linhas = [
      ...responder(resultado()).querySelectorAll(
        '.tabela--geral tbody tr, .tabela--geral tfoot tr',
      ),
    ].map((tr) => texto(tr));

    expect(linhas).toEqual([
      'Positivo 200 50%',
      'Neutro 100 25%',
      'Negativo 100 25%',
      'Total 400 100%',
    ]);
  });

  it('mostra cada tema com palavras-chave, % de negativos e o comentário representativo', () => {
    montar();
    const tema = responder(resultado()).querySelector('.tema')!;

    expect(texto(tema.querySelector('h3'))).toBe('Preço');
    expect(texto(tema.querySelector('.tema__palavras'))).toBe('preço · caro · valor');
    expect(texto(tema.querySelector('.tema__negativos'))).toBe('50% negativos');
    expect(texto(tema.querySelector('blockquote'))).toContain('Achei o preço alto demais');
    // Nenhum dado do autor no papel, nem o hash.
    expect(texto(tema)).not.toContain('ffff');
  });

  it('explica a falta de temas quando há menos de 100 comentários', () => {
    montar();
    const el = responder(
      resultado({
        temas: [],
        distribuicao: { positivo: 40, neutro: 20, negativo: 20, total: 80 },
      }),
    );

    const secao = texto(el.querySelector('#sec-temas')!.parentElement);
    expect(secao).toContain('80 comentários analisados, abaixo do mínimo de 100');
    expect(el.querySelector('.tema')).toBeNull();
  });

  it('lista os insights da execução e da campanha com o tamanho da amostra', () => {
    montar();
    const insights = [...responder(resultado()).querySelectorAll('.insight')].map((i) => texto(i));

    expect(insights).toEqual([
      'O tema “Preço” é o que mais concentra críticas. Amostra: 60 comentários (mínimo exigido: 30)',
      'A proporção de negativos subiu desde a coleta anterior. Amostra: 400 comentários (mínimo exigido: 100)',
    ]);
  });

  it('diz que não há insight em vez de deixar a seção vazia', () => {
    montar();
    const secao = texto(
      responder(resultado({ insights: [], insights_da_campanha: [] })).querySelector(
        '#sec-insights',
      )!.parentElement,
    );

    expect(secao).toContain('Nenhuma afirmação atingiu a amostra mínima');
    expect(secao).toContain('primeira coleta da campanha');
  });

  it('nomeia o classificador e as limitações na seção de leitura', () => {
    montar();
    const secao = texto(responder(resultado()).querySelector('#sec-leitura')!.parentElement);

    expect(secao).toContain('lexico-sentilex 1.0.0');
    expect(secao).toContain('quem comentou');
    expect(secao).toContain('neutra é a mais difícil');
  });

  it('dá ao documento um título que vira o nome do PDF', () => {
    montar();
    responder(resultado());

    expect(TestBed.inject(Title).getTitle()).toBe('Relatório — Campanha Verão — execução 12');
  });

  it('imprime pelo navegador ao clicar no botão', () => {
    montar();
    const imprimir = vi.spyOn(window, 'print').mockImplementation(() => undefined);
    const el = responder(resultado());

    const botao = [...el.querySelectorAll('button')].find((b) =>
      texto(b).includes('Imprimir / salvar em PDF'),
    )!;
    botao.click();

    expect(imprimir).toHaveBeenCalledOnce();
  });

  it('execução de outro usuário (404) não mostra relatório nenhum', () => {
    montar();
    httpMock
      .expectOne(URL_RESULTADO)
      .flush({ detail: 'Execução não encontrada.' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    expect(texto(el.querySelector('[role="alert"]'))).toContain(
      'Esta execução não tem resultados disponíveis.',
    );
    expect(el.querySelector('article')).toBeNull();
    expect(el.querySelector('button')).toBeNull();
  });

  it('no servidor não busca dados nem chama window.print', () => {
    montar('server');
    const imprimir = vi.spyOn(window, 'print').mockImplementation(() => undefined);
    fixture.detectChanges();

    httpMock.expectNone(URL_RESULTADO);
    (fixture.componentInstance as unknown as { imprimir: () => void }).imprimir();
    expect(imprimir).not.toHaveBeenCalled();
  });
});
