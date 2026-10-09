import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { ResultadoExecucao } from '../../core/api/resultados.models';
import { ResultadosHttpService, ResultadosService } from '../../core/api/resultados.service';
import { RESULTADOS_DEMO } from '../../core/mock/dados-demo';
import { MINIMO_COMENTARIOS_PARA_TEMAS, Resultado } from './resultado';

describe('Resultado', () => {
  let httpMock: HttpTestingController;

  afterEach(() => httpMock.verify());

  function renderizar(resultado: ResultadoExecucao): HTMLElement {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ResultadosService, useClass: ResultadosHttpService },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ id: '12' }) } },
        },
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(Resultado);
    httpMock.expectOne(`${environment.apiBaseUrl}/execucoes/12/resultado`).flush(resultado);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function semTemas(total: number): ResultadoExecucao {
    const base = RESULTADOS_DEMO.get(12)!;
    return { ...base, temas: [], distribuicao: { ...base.distribuicao, total } };
  }

  it('sem tema por falta de volume, diz o mínimo e quantos comentários a execução tem', () => {
    const tela = renderizar(semTemas(40));

    const nota = tela.querySelector('[data-testid="sem-temas"]')!.textContent!;
    expect(nota).toContain(`a partir de ${MINIMO_COMENTARIOS_PARA_TEMAS} comentários`);
    expect(nota).toContain('tem 40');
    expect(nota).not.toContain('ainda não roda');
  });

  it('sem tema com volume suficiente, explica que sobrou pouco texto', () => {
    const tela = renderizar(semTemas(500));

    const nota = tela.querySelector('[data-testid="sem-temas"]')!.textContent!;
    expect(nota).toContain('sobrou pouco texto');
    expect(nota).not.toContain('a partir de');
  });

  it('com temas, não mostra a nota', () => {
    const tela = renderizar(RESULTADOS_DEMO.get(12)!);

    expect(tela.querySelector('[data-testid="sem-temas"]')).toBeNull();
  });

  it('"Baixar relatório" está habilitado e abre a página de impressão da execução', () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ResultadosService, useClass: ResultadosHttpService },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ id: '12' }) } },
        },
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(Resultado);

    httpMock
      .expectOne(`${environment.apiBaseUrl}/execucoes/12/resultado`)
      .flush(RESULTADOS_DEMO.get(12)!);
    fixture.detectChanges();

    const link = [...(fixture.nativeElement as HTMLElement).querySelectorAll('a')].find((a) =>
      a.textContent?.includes('Baixar relatório'),
    );
    expect(link).toBeDefined();
    expect(link!.getAttribute('href')).toBe('/resultados/12/relatorio');
    expect(link!.hasAttribute('disabled')).toBe(false);
  });
});
