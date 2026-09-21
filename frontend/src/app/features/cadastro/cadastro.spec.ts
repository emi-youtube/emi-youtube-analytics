import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { Cadastro } from './cadastro';

const AUTH = `${environment.apiBaseUrl}/auth`;

describe('Cadastro', () => {
  let fixture: ComponentFixture<Cadastro>;
  let httpMock: HttpTestingController;
  /** Destinos passados ao Router, na ordem. */
  let navegou: string[];

  /** Acesso ao que o template consome — `protected` é visível em runtime. */
  function componente(): {
    form: Cadastro['form'];
    erro: Cadastro['erro'];
    contaCriada: Cadastro['contaCriada'];
    enviar: () => void;
  } {
    return fixture.componentInstance as unknown as ReturnType<typeof componente>;
  }

  function preencher(senha = 'senha-forte-1', confirmacao = senha): void {
    componente().form.setValue({
      nome: 'Marina Rocha',
      email: 'marina@empresa.com.br',
      senha,
      confirmacao,
    });
  }

  beforeEach(() => {
    localStorage.clear();
    navegou = [];

    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });

    vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockImplementation((destino) => {
      navegou.push(destino.toString());
      return Promise.resolve(true);
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Cadastro);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('não envia quando a confirmação difere da senha', () => {
    preencher('senha-forte-1', 'senha-forte-2');

    componente().enviar();

    httpMock.expectNone(`${AUTH}/registrar`);
  });

  it('registra, entra automaticamente e vai para /inicio', () => {
    preencher();

    componente().enviar();

    httpMock.expectOne(`${AUTH}/registrar`).flush(
      {
        id_usuario: 7,
        nome: 'Marina Rocha',
        email: 'marina@empresa.com.br',
        papel: 'usuario_pme',
        criado_em: '2026-09-21T00:00:00',
      },
      { status: 201, statusText: 'Created' },
    );

    const login = httpMock.expectOne(`${AUTH}/login`);
    expect(login.request.body).toEqual({
      email: 'marina@empresa.com.br',
      senha: 'senha-forte-1',
    });
    login.flush({ access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer' });

    httpMock.expectOne(`${AUTH}/eu`).flush({
      id_usuario: 7,
      nome: 'Marina Rocha',
      email: 'marina@empresa.com.br',
      papel: 'usuario_pme',
      criado_em: '2026-09-21T00:00:00',
    });

    expect(navegou).toEqual(['/inicio']);
  });

  it('traduz o 409 de e-mail já cadastrado', () => {
    preencher();

    componente().enviar();

    httpMock
      .expectOne(`${AUTH}/registrar`)
      .flush(
        { detail: 'Já existe uma conta com este e-mail.' },
        { status: 409, statusText: 'Conflict' },
      );

    expect(componente().erro()).toContain('Já existe uma conta com este e-mail');
    expect(componente().contaCriada()).toBe(false);
  });

  it('avisa que a conta existe quando só o login automático falha', () => {
    preencher();

    componente().enviar();

    httpMock
      .expectOne(`${AUTH}/registrar`)
      .flush({ id_usuario: 7 }, { status: 201, statusText: 'Created' });
    httpMock
      .expectOne(`${AUTH}/login`)
      .flush({ detail: 'erro' }, { status: 500, statusText: 'Server Error' });

    expect(componente().contaCriada()).toBe(true);
    expect(componente().erro()).toContain('Sua conta foi criada');
    expect(navegou).toEqual([]);
  });
});
