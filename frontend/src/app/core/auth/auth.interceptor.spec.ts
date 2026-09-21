import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { describe, beforeEach, afterEach, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';

const AUTH = `${environment.apiBaseUrl}/auth`;

describe('authInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let auth: AuthService;
  let navigate: ReturnType<typeof vi.fn>;

  /** Deixa a sessão pronta: access token em memória, refresh no storage. */
  function autenticar(accessToken = 'access-1', refreshToken = 'refresh-1'): void {
    auth.login({ email: 'a@b.com', senha: 'x' }).subscribe({ error: () => undefined });
    httpMock
      .expectOne(`${AUTH}/login`)
      .flush({ access_token: accessToken, refresh_token: refreshToken, token_type: 'bearer' });
    // `login` encadeia GET /auth/eu logo depois.
    httpMock.expectOne(`${AUTH}/eu`).flush({
      id_usuario: 1,
      nome: 'Marina Rocha',
      email: 'a@b.com',
      papel: 'usuario_pme',
      criado_em: '2026-09-20T00:00:00',
    });
  }

  beforeEach(() => {
    localStorage.clear();
    navigate = vi.fn().mockResolvedValue(true);

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: Router, useValue: { navigate, url: '/execucoes' } },
      ],
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('anexa o access token nas requisições da aplicação', () => {
    autenticar();

    http.get('/api/v1/execucoes').subscribe();

    const req = httpMock.expectOne('/api/v1/execucoes');
    expect(req.request.headers.get('Authorization')).toBe('Bearer access-1');
    req.flush({});
  });

  it('não tenta refresh quando o próprio login devolve 401', () => {
    // A tela de login manda credencial errada: o 401 é a resposta legítima e
    // precisa chegar inteiro na tela. Se o interceptor agisse aqui, tentaria um
    // refresh — e o 401 desse refresh entraria em laço.
    const erro = vi.fn();
    auth.login({ email: 'a@b.com', senha: 'errada' }).subscribe({ error: erro });

    const req = httpMock.expectOne(`${AUTH}/login`);
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush(
      { detail: 'E-mail ou senha inválidos.' },
      { status: 401, statusText: 'Unauthorized' },
    );

    // Nenhuma chamada a /auth/refresh: o httpMock.verify() do afterEach reprova
    // se alguma tiver sobrado.
    expect(erro).toHaveBeenCalled();
    expect(erro.mock.calls[0][0].error.detail).toBe('E-mail ou senha inválidos.');
  });

  it('no 401 renova o token e repete a requisição original', () => {
    autenticar();

    const resultado = vi.fn();
    http.get('/api/v1/execucoes').subscribe(resultado);

    httpMock
      .expectOne('/api/v1/execucoes')
      .flush({ detail: 'Não autenticado.' }, { status: 401, statusText: 'Unauthorized' });

    const refresh = httpMock.expectOne(`${AUTH}/refresh`);
    expect(refresh.request.body).toEqual({ refresh_token: 'refresh-1' });
    refresh.flush({ access_token: 'access-2', token_type: 'bearer' });

    const repetida = httpMock.expectOne('/api/v1/execucoes');
    expect(repetida.request.headers.get('Authorization')).toBe('Bearer access-2');
    repetida.flush({ total: 3 });

    expect(resultado).toHaveBeenCalledWith({ total: 3 });
    expect(auth.token()).toBe('access-2');
  });

  it('dispara um único refresh quando várias requisições tomam 401 juntas', () => {
    autenticar();

    http.get('/api/v1/execucoes').subscribe();
    http.get('/api/v1/modelos').subscribe();

    httpMock.expectOne('/api/v1/execucoes').flush({}, { status: 401, statusText: 'Unauthorized' });
    httpMock.expectOne('/api/v1/modelos').flush({}, { status: 401, statusText: 'Unauthorized' });

    // O ponto do teste: uma chamada de refresh, não duas.
    httpMock.expectOne(`${AUTH}/refresh`).flush({ access_token: 'access-2', token_type: 'bearer' });

    httpMock.expectOne('/api/v1/execucoes').flush({});
    httpMock.expectOne('/api/v1/modelos').flush({});
  });

  it('com refresh recusado, limpa a sessão e manda para o login', () => {
    autenticar();

    const erro = vi.fn();
    http.get('/api/v1/execucoes').subscribe({ error: erro });

    httpMock.expectOne('/api/v1/execucoes').flush({}, { status: 401, statusText: 'Unauthorized' });
    httpMock
      .expectOne(`${AUTH}/refresh`)
      .flush(
        { detail: 'Refresh token inválido ou expirado.' },
        { status: 401, statusText: 'Unauthorized' },
      );

    expect(auth.isAuthenticated()).toBe(false);
    expect(auth.hasPersistedSession()).toBe(false);
    expect(navigate).toHaveBeenCalledWith(['/login'], {
      queryParams: { returnUrl: '/execucoes' },
    });
    // Quem chamou recebe o 401 da SUA requisição, não o do refresh.
    expect(erro).toHaveBeenCalled();
    expect(erro.mock.calls[0][0].url).toContain('/api/v1/execucoes');
  });
});
