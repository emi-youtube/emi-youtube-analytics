import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { RedefinirSenha } from './redefinir-senha';

const AUTH = `${environment.apiBaseUrl}/auth`;

describe('RedefinirSenha', () => {
  let fixture: ComponentFixture<RedefinirSenha>;
  let httpMock: HttpTestingController;

  function componente(): {
    form: RedefinirSenha['form'];
    concluido: RedefinirSenha['concluido'];
    erro: RedefinirSenha['erro'];
    enviar: () => void;
  } {
    return fixture.componentInstance as unknown as ReturnType<typeof componente>;
  }

  function montar(token: string | null): void {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: convertToParamMap(token ? { token } : {}) },
          },
        },
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RedefinirSenha);
  }

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('sem token no link avisa e não mostra o formulário', () => {
    montar(null);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('link está incompleto');
    expect(fixture.nativeElement.querySelector('#nova_senha')).toBeNull();
  });

  it('não envia quando as senhas divergem', () => {
    montar('tok');
    componente().form.setValue({ nova_senha: 'NovaSenha456', confirmacao: 'Outra999x' });

    componente().enviar();

    httpMock.expectNone(`${AUTH}/redefinir-senha`);
  });

  it('redefine com o token do link e encerra a sessão local', () => {
    montar('tok-abc');
    localStorage.setItem('emi.refresh_token', 'refresh-antigo');
    componente().form.setValue({ nova_senha: 'NovaSenha456', confirmacao: 'NovaSenha456' });

    componente().enviar();

    const pedido = httpMock.expectOne(`${AUTH}/redefinir-senha`);
    expect(pedido.request.body).toEqual({ token: 'tok-abc', nova_senha: 'NovaSenha456' });
    pedido.flush(null, { status: 204, statusText: 'No Content' });

    expect(componente().concluido()).toBe(true);
    expect(localStorage.getItem('emi.refresh_token')).toBeNull();
  });

  it('link vencido ou usado mostra a mensagem do servidor', () => {
    montar('tok-velho');
    componente().form.setValue({ nova_senha: 'NovaSenha456', confirmacao: 'NovaSenha456' });

    componente().enviar();

    httpMock
      .expectOne(`${AUTH}/redefinir-senha`)
      .flush(
        { detail: 'Link de redefinição inválido ou expirado.' },
        { status: 400, statusText: 'Bad Request' },
      );

    expect(componente().concluido()).toBe(false);
    expect(componente().erro()).toBe('Link de redefinição inválido ou expirado.');
  });
});
