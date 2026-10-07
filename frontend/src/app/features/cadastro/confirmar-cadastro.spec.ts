import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { ConfirmarCadastro } from './confirmar-cadastro';

const AUTH = `${environment.apiBaseUrl}/auth`;

const USUARIO = {
  id_usuario: 7,
  nome: 'Marina Rocha',
  email: 'marina@empresa.com.br',
  papel: 'usuario_pme',
  papel_empresa: 'dono',
  empresa: { id_empresa: 3, nome: 'Loja da Marina' },
  criado_em: '2026-10-07T00:00:00',
};

describe('ConfirmarCadastro', () => {
  let fixture: ComponentFixture<ConfirmarCadastro>;
  let httpMock: HttpTestingController;
  let navegou: string[];

  function montar(token?: string): HTMLElement {
    localStorage.clear();
    navegou = [];
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: convertToParamMap(token ? { token } : {}) } },
        },
      ],
    });
    vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockImplementation((destino) => {
      navegou.push(destino.toString());
      return Promise.resolve(true);
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ConfirmarCadastro);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('confirma ao abrir, guarda a sessão e vai para /inicio', () => {
    montar('tok-1');

    const confirmacao = httpMock.expectOne(`${AUTH}/confirmar-cadastro`);
    expect(confirmacao.request.body).toEqual({ token: 'tok-1' });
    confirmacao.flush({ access_token: 'a-1', refresh_token: 'r-1', token_type: 'bearer' });
    httpMock.expectOne(`${AUTH}/eu`).flush(USUARIO);

    expect(navegou).toEqual(['/inicio']);
  });

  it('link vencido ou já usado mostra o erro e o caminho de volta ao cadastro', () => {
    const tela = montar('tok-velho');

    httpMock
      .expectOne(`${AUTH}/confirmar-cadastro`)
      .flush(
        { detail: 'Link de confirmação inválido ou expirado. Faça o cadastro de novo.' },
        { status: 400, statusText: 'Bad Request' },
      );
    fixture.detectChanges();

    expect(tela.querySelector('[data-testid="confirmacao-erro"]')?.textContent).toContain(
      'inválido ou expirado',
    );
    expect(tela.querySelector('a[href="/cadastro"]')).not.toBeNull();
    expect(navegou).toEqual([]);
  });

  it('e-mail que ganhou conta no meio do caminho manda entrar', () => {
    const tela = montar('tok-1');

    httpMock
      .expectOne(`${AUTH}/confirmar-cadastro`)
      .flush(
        { detail: 'Já existe uma conta com este e-mail.' },
        { status: 409, statusText: 'Conflict' },
      );
    fixture.detectChanges();

    expect(tela.textContent).toContain('Este e-mail já tem conta. Entre com ela.');
  });

  it('sem token não chama a API', () => {
    const tela = montar();

    httpMock.expectNone(`${AUTH}/confirmar-cadastro`);
    expect(tela.textContent).toContain('Este link está incompleto');
  });
});
