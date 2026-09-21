import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { Execucao, StatusExecucao } from '../../core/api/execucoes.models';
import { Execucoes } from './execucoes';

const EXECUCOES = `${environment.apiBaseUrl}/execucoes`;
const MODELOS = `${environment.apiBaseUrl}/modelos-analise`;

/** Mesmo intervalo de `INTERVALO_POLLING_MS` no componente. */
const INTERVALO = 3000;

function execucao(status: StatusExecucao, id = 1): Execucao {
  return {
    id_execucao: id,
    id_modelo: 1,
    status,
    iniciado_em: status === 'pendente' ? null : '2026-09-21T13:12:00',
    concluido_em: status === 'concluida' || status === 'erro' ? '2026-09-21T13:13:00' : null,
  };
}

describe('Execucoes', () => {
  let fixture: ComponentFixture<Execucoes>;
  let httpMock: HttpTestingController;

  /** `protected` só existe no compilador; em runtime os membros estão aí. */
  function componente(): {
    execucoes: Execucoes['execucoes'];
    erroDisparo: Execucoes['erroDisparo'];
    resumo: Execucoes['resumo'];
    modelosOcupados: Execucoes['modelosOcupados'];
    modeloEscolhido: number | null;
    disparar: () => void;
  } {
    return fixture.componentInstance as unknown as ReturnType<typeof componente>;
  }

  /** Responde à carga inicial (execuções + modelos em paralelo). */
  function carregarCom(execucoes: Execucao[]): void {
    httpMock.expectOne(EXECUCOES).flush(execucoes);
    httpMock.expectOne(MODELOS).flush([
      {
        id_modelo: 1,
        id_usuario: 1,
        nome: 'Campanha Verão',
        termo_pesquisa: 'tênis',
        filtros: { videos: ['dQw4w9WgXcQ'] },
        criado_em: '2026-09-21T10:00:00',
      },
    ]);
  }

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Execucoes);
  });

  afterEach(() => {
    httpMock.verify();
    vi.useRealTimers();
  });

  it('não faz polling quando nada está ativo', () => {
    carregarCom([execucao('concluida')]);

    vi.advanceTimersByTime(INTERVALO * 3);

    httpMock.expectNone(`${EXECUCOES}/1`);
  });

  it('consulta a execução ativa a cada intervalo e para quando ela conclui', () => {
    carregarCom([execucao('pendente')]);

    // 1ª volta: ainda rodando.
    vi.advanceTimersByTime(INTERVALO);
    httpMock.expectOne(`${EXECUCOES}/1`).flush(execucao('processando'));
    expect(componente().execucoes()[0].status).toBe('processando');

    // 2ª volta: terminou.
    vi.advanceTimersByTime(INTERVALO);
    httpMock.expectOne(`${EXECUCOES}/1`).flush(execucao('concluida'));
    expect(componente().execucoes()[0].status).toBe('concluida');
    expect(componente().resumo()).toEqual({
      pendente: 0,
      processando: 0,
      concluida: 1,
      erro: 0,
    });

    // Daqui em diante o status não muda mais: nenhuma consulta nova.
    vi.advanceTimersByTime(INTERVALO * 5);
    httpMock.expectNone(`${EXECUCOES}/1`);
  });

  it('para o polling também quando a execução termina em erro', () => {
    carregarCom([execucao('processando')]);

    vi.advanceTimersByTime(INTERVALO);
    httpMock.expectOne(`${EXECUCOES}/1`).flush(execucao('erro'));

    vi.advanceTimersByTime(INTERVALO * 3);
    httpMock.expectNone(`${EXECUCOES}/1`);
  });

  it('mostra a execução aceita na hora, sem esperar o worker', () => {
    carregarCom([]);

    componente().modeloEscolhido = 1;
    componente().disparar();

    httpMock
      .expectOne({ method: 'POST', url: EXECUCOES })
      .flush(execucao('pendente', 7), { status: 202, statusText: 'Accepted' });

    expect(componente().execucoes()).toHaveLength(1);
    expect(componente().execucoes()[0].status).toBe('pendente');
    // E o acompanhamento começa por conta da execução recém-criada.
    vi.advanceTimersByTime(INTERVALO);
    httpMock.expectOne(`${EXECUCOES}/7`).flush(execucao('concluida', 7));
  });

  it('explica o 409 do disparo e recarrega a lista', () => {
    carregarCom([]);

    componente().modeloEscolhido = 1;
    componente().disparar();

    httpMock
      .expectOne({ method: 'POST', url: EXECUCOES })
      .flush(
        { detail: 'Este modelo já possui uma execução em andamento.' },
        { status: 409, statusText: 'Conflict' },
      );

    expect(componente().erroDisparo()).toContain('já tem uma execução em andamento');

    // A lista é relida para a tela refletir a execução que a outra aba criou.
    httpMock.expectOne(EXECUCOES).flush([execucao('processando', 9)]);
    expect(componente().modelosOcupados().has(1)).toBe(true);

    vi.advanceTimersByTime(INTERVALO);
    httpMock.expectOne(`${EXECUCOES}/9`).flush(execucao('concluida', 9));
  });

  it('segue acompanhando depois de uma falha de rede numa volta', () => {
    carregarCom([execucao('processando')]);

    vi.advanceTimersByTime(INTERVALO);
    httpMock.expectOne(`${EXECUCOES}/1`).error(new ProgressEvent('erro de rede'));
    expect(componente().execucoes()[0].status).toBe('processando');

    vi.advanceTimersByTime(INTERVALO);
    httpMock.expectOne(`${EXECUCOES}/1`).flush(execucao('concluida'));
    expect(componente().execucoes()[0].status).toBe('concluida');
  });
});
