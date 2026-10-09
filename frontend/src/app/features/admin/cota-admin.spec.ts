import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { CotaAdmin as CotaAdminDados } from '../../core/api/admin.models';
import { CotaAdmin } from './cota-admin';

const ROTA = `${environment.apiBaseUrl}/admin/cota-youtube?dias=30`;

function dados(campos: Partial<CotaAdminDados> = {}): CotaAdminDados {
  const historico = Array.from({ length: 30 }, (_, i) => ({
    // 30 dias terminando em 09/10/2026.
    dia: new Date(Date.UTC(2026, 8, 10 + i)).toISOString().slice(0, 10),
    unidades: i === 29 ? 2640 : i === 27 ? 300 : 0,
  }));
  return {
    dia_da_cota: '2026-10-09',
    renova_em: '2026-10-10T07:00:00Z',
    limite: 10000,
    reserva: 500,
    fatia_por_empresa: 2000,
    teto_folga: 7000,
    usado_hoje: 2640,
    ajuste_hoje: 100,
    dias: 30,
    empresas: [
      {
        id_empresa: 1,
        nome: 'Loja Grande',
        unidades_hoje: 2500,
        unidades_periodo: 2800,
        execucoes_aguardando: 2,
        acima_da_fatia: true,
      },
      {
        id_empresa: 2,
        nome: 'Loja Pequena',
        unidades_hoje: 40,
        unidades_periodo: 140,
        execucoes_aguardando: 0,
        acima_da_fatia: false,
      },
    ],
    historico,
    pico_no_periodo: 2640,
    media_no_periodo: 98,
    ...campos,
  };
}

describe('CotaAdmin', () => {
  let fixture: ComponentFixture<CotaAdmin>;
  let httpMock: HttpTestingController;

  function tela(): HTMLElement {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(CotaAdmin);
  });

  afterEach(() => httpMock.verify());

  it('mostra o dia, as empresas e quem passou da fatia', () => {
    httpMock.expectOne(ROTA).flush(dados());
    const texto = tela().textContent ?? '';

    expect(texto).toContain('2.640');
    expect(texto).toContain('de 10.000 unidades');
    expect(texto).toContain('Loja Grande');
    expect(texto).toContain('acima da fatia');
    expect(texto).toContain('125%'); // 2.500 de uma fatia de 2.000
    expect(texto).toContain('unidades de ajuste');
    const linhas = tela().querySelectorAll('tbody tr');
    expect(linhas.length).toBe(2);
    expect(linhas[1].textContent).not.toContain('acima da fatia');
  });

  it('tem uma barra por dia e a leitura começa em hoje', () => {
    httpMock.expectOne(ROTA).flush(dados());

    expect(tela().querySelectorAll('.historico__coluna').length).toBe(30);
    expect(tela().querySelector('.historico__leitura')?.textContent).toContain('2.640 unidades');
  });

  it('passar o cursor num dia mostra o valor dele', () => {
    httpMock.expectOne(ROTA).flush(dados());
    const colunas = tela().querySelectorAll<HTMLElement>('.historico__coluna');

    colunas[27].dispatchEvent(new Event('mouseenter'));

    expect(tela().querySelector('.historico__leitura')?.textContent).toContain('300 unidades');
  });

  it('sem uso no período, diz isso em vez de mostrar uma tabela vazia', () => {
    httpMock.expectOne(ROTA).flush(dados({ empresas: [], usado_hoje: 0, ajuste_hoje: 0 }));

    expect(tela().querySelector('tbody')).toBeNull();
    expect(tela().textContent).toContain('Nenhuma empresa usou a cota');
  });

  it('403 vira mensagem, não tela quebrada', () => {
    httpMock
      .expectOne(ROTA)
      .flush({ detail: 'Acesso restrito a administradores.' }, { status: 403, statusText: 'x' });

    expect(tela().querySelector('[role="alert"]')).not.toBeNull();
  });
});
