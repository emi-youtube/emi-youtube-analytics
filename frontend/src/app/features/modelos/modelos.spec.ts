import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { ModeloAnalise } from '../../core/api/modelos.models';
import { ModeloForm } from './modelo-form';
import { Modelos } from './modelos';

const URL = `${environment.apiBaseUrl}/modelos-analise`;

function modelo(id_modelo: number, pode_alterar: boolean): ModeloAnalise {
  return {
    id_modelo,
    id_usuario: 7,
    nome: `Campanha ${id_modelo}`,
    termo_pesquisa: '',
    filtros: { videos: ['dQw4w9WgXcQ'] },
    criado_em: '2026-10-01T10:00:00',
    autor_nome: 'Ana Souza',
    pode_alterar,
  };
}

describe('Modelos (lista)', () => {
  let httpMock: HttpTestingController;

  afterEach(() => httpMock.verify());

  function montar(modelos: ModeloAnalise[]): HTMLElement {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(Modelos);
    httpMock.expectOne(URL).flush(modelos);
    fixture.detectChanges();
    return fixture.nativeElement;
  }

  it('mostra quem criou cada modelo', () => {
    const tela = montar([modelo(1, true)]);

    expect(tela.querySelector('[data-testid="autor"]')?.textContent).toContain(
      'criado por Ana Souza',
    );
  });

  it('editar e excluir só aparecem em pode_alterar', () => {
    const tela = montar([modelo(1, true), modelo(2, false)]);

    const acoes = Array.from(tela.querySelectorAll('.modelo__acoes')).map((el) =>
      el.textContent?.replace(/\s+/g, ' ').trim(),
    );
    expect(acoes[0]).toContain('Editar');
    expect(acoes[0]).toContain('Excluir');
    expect(acoes[1]).toBe('');
  });
});

describe('ModeloForm (edição de modelo de colega)', () => {
  let httpMock: HttpTestingController;

  afterEach(() => httpMock.verify());

  function montar(podeAlterar: boolean) {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ id: '5' }) } },
        },
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(ModeloForm);
    httpMock.expectOne(`${URL}/5`).flush(modelo(5, podeAlterar));
    fixture.detectChanges();
    return fixture;
  }

  it('sem permissão: avisa quem é o autor, trava o formulário e não salva', () => {
    const fixture = montar(false);
    const tela: HTMLElement = fixture.nativeElement;

    expect(tela.querySelector('[data-testid="somente-leitura"]')?.textContent).toContain(
      'Ana Souza',
    );
    const botoes = Array.from(tela.querySelectorAll('.acoes button')) as HTMLButtonElement[];
    expect(botoes.every((b) => b.disabled)).toBe(true);

    (fixture.componentInstance as unknown as { salvar: (e: boolean) => void }).salvar(false);
    httpMock.expectNone({ method: 'PATCH', url: `${URL}/5` });
  });

  it('avisa, antes de executar, que os comentários ficam só 30 dias (ADR-015)', () => {
    const tela: HTMLElement = montar(true).nativeElement;

    const aviso = tela.querySelector('[data-testid="aviso-prazo-comentarios"]')?.textContent ?? '';
    expect(aviso).toContain('até 30 dias');
    expect(aviso).toContain('políticas da API do YouTube');
    expect(aviso).toContain('percentuais, os temas e os indicadores');
  });

  it('com permissão: formulário livre', () => {
    const fixture = montar(true);
    const tela: HTMLElement = fixture.nativeElement;

    expect(tela.querySelector('[data-testid="somente-leitura"]')).toBeNull();
    const botoes = Array.from(tela.querySelectorAll('.acoes button')) as HTMLButtonElement[];
    expect(botoes.some((b) => b.disabled)).toBe(false);
  });
});
