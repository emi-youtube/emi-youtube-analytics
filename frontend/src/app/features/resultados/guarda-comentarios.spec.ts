import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { GuardaComentarios } from './guarda-comentarios';

describe('GuardaComentarios (prazo de 30 dias, ADR-015)', () => {
  let httpMock: HttpTestingController;

  afterEach(() => httpMock.verify());

  function montar(entradas: {
    disponiveisAte?: string | null;
    apagadosEm?: string | null;
    idModelo?: number | null;
    impressao?: boolean;
  }) {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(GuardaComentarios);
    for (const [nome, valor] of Object.entries(entradas)) {
      fixture.componentRef.setInput(nome, valor);
    }
    fixture.detectChanges();
    return fixture;
  }

  function texto(fixture: { nativeElement: HTMLElement }): string {
    return fixture.nativeElement.textContent?.replace(/\s+/g, ' ') ?? '';
  }

  it('antes do prazo, diz até quando os comentários ficam', () => {
    const fixture = montar({ disponiveisAte: '2026-10-23T10:00:00Z' });

    expect(texto(fixture)).toContain('ficam disponíveis até 23/10/2026');
    expect(fixture.nativeElement.querySelector('button')).toBeNull();
  });

  it('depois do expurgo, explica o motivo e diz que os resultados continuam', () => {
    const fixture = montar({ apagadosEm: '2026-10-23T10:30:00Z', idModelo: 3 });

    const conteudo = texto(fixture);
    expect(conteudo).toContain('foram apagados');
    expect(conteudo).toContain('mais de 30 dias');
    expect(conteudo).toContain('23/10/2026');
    expect(conteudo).toContain('continuam valendo');
  });

  it('"Refazer a análise" dispara uma execução nova do mesmo modelo', () => {
    const fixture = montar({ apagadosEm: '2026-10-23T10:30:00Z', idModelo: 3 });
    const navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    (fixture.nativeElement.querySelector('button') as HTMLButtonElement).click();

    const pedido = httpMock.expectOne(`${environment.apiBaseUrl}/execucoes`);
    expect(pedido.request.method).toBe('POST');
    expect(pedido.request.body).toEqual({ id_modelo: 3 });
    pedido.flush({ id_execucao: 99, id_modelo: 3, status: 'pendente' });
    expect(navegar).toHaveBeenCalledWith(['/execucoes']);
  });

  it('no relatório impresso não há botão', () => {
    const fixture = montar({ apagadosEm: '2026-10-23T10:30:00Z', idModelo: 3, impressao: true });

    expect(fixture.nativeElement.querySelector('button')).toBeNull();
    expect(texto(fixture)).toContain('foram apagados');
  });

  it('sem execução iniciada, não mostra nada', () => {
    const fixture = montar({});

    expect(texto(fixture).trim()).toBe('');
  });
});
