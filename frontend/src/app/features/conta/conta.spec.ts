import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { Conta } from './conta';

const AUTH = `${environment.apiBaseUrl}/auth`;

describe('Conta', () => {
  let fixture: ComponentFixture<Conta>;
  let httpMock: HttpTestingController;

  function componente(): {
    form: Conta['form'];
    sucesso: Conta['sucesso'];
    erro: Conta['erro'];
    trocar: () => void;
  } {
    return fixture.componentInstance as unknown as ReturnType<typeof componente>;
  }

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Conta);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('não envia nova senha curta', () => {
    componente().form.setValue({
      senha_atual: 'SenhaForte123',
      nova_senha: 'curta',
      confirmacao: 'curta',
    });

    componente().trocar();

    httpMock.expectNone(`${AUTH}/trocar-senha`);
  });

  it('troca a senha e guarda o par novo devolvido', () => {
    componente().form.setValue({
      senha_atual: 'SenhaForte123',
      nova_senha: 'NovaSenha456',
      confirmacao: 'NovaSenha456',
    });

    componente().trocar();

    const pedido = httpMock.expectOne(`${AUTH}/trocar-senha`);
    expect(pedido.request.body).toEqual({
      senha_atual: 'SenhaForte123',
      nova_senha: 'NovaSenha456',
    });
    pedido.flush({ access_token: 'access-9', refresh_token: 'refresh-9', token_type: 'bearer' });

    expect(componente().sucesso()).toBe(true);
    // Sem guardar o refresh novo, a própria aba cairia no próximo refresh.
    expect(localStorage.getItem('emi.refresh_token')).toBe('refresh-9');
    expect(componente().form.getRawValue().senha_atual).toBe('');
  });

  it('mostra o erro de senha atual incorreta', () => {
    componente().form.setValue({
      senha_atual: 'errada-123',
      nova_senha: 'NovaSenha456',
      confirmacao: 'NovaSenha456',
    });

    componente().trocar();

    httpMock
      .expectOne(`${AUTH}/trocar-senha`)
      .flush({ detail: 'Senha atual incorreta.' }, { status: 400, statusText: 'Bad Request' });

    expect(componente().sucesso()).toBe(false);
    expect(componente().erro()).toBe('Senha atual incorreta.');
  });
});
