import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { ResultadosHttpService, ResultadosService } from '../../core/api/resultados.service';
import { RESULTADOS_DEMO } from '../../core/mock/dados-demo';
import { Resultado } from './resultado';

describe('Resultado', () => {
  let httpMock: HttpTestingController;

  afterEach(() => httpMock.verify());

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
