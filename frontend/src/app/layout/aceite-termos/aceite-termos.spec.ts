import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth/auth.service';
import { AceiteTermos } from './aceite-termos';

const API = environment.apiBaseUrl;

describe('AceiteTermos', () => {
  let fixture: ComponentFixture<AceiteTermos>;
  let httpMock: HttpTestingController;
  let auth: AuthService;
  let navegou: unknown[];

  /** Sessão com termos pendentes, como `GET /auth/eu` devolve para conta antiga. */
  function entrar(): void {
    auth.login({ email: 'a@b.com', senha: 'x' }).subscribe();
    httpMock
      .expectOne(`${API}/auth/login`)
      .flush({ access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer' });
    httpMock.expectOne(`${API}/auth/eu`).flush({
      id_usuario: 1,
      nome: 'Marina',
      email: 'a@b.com',
      papel: 'usuario_pme',
      papel_empresa: 'membro',
      empresa: { id_empresa: 1, nome: 'Loja' },
      criado_em: '2026-09-20T00:00:00',
      termos_pendentes: true,
    });
  }

  beforeEach(() => {
    localStorage.clear();
    navegou = [];
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    vi.spyOn(TestBed.inject(Router), 'navigate').mockImplementation((destino) => {
      navegou.push(destino);
      return Promise.resolve(true);
    });
    httpMock = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    entrar();
    fixture = TestBed.createComponent(AceiteTermos);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  function botao(texto: string): HTMLButtonElement {
    const botoes = Array.from(
      fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>,
    );
    return botoes.find((b) => b.textContent?.includes(texto))!;
  }

  it('é um diálogo modal com o resumo e os links do texto completo', () => {
    const dialogo: HTMLElement = fixture.nativeElement.querySelector('[role="alertdialog"]');
    expect(dialogo.getAttribute('aria-modal')).toBe('true');
    expect(dialogo.textContent).toContain('pseudonimizado');
    const links = Array.from(dialogo.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(links).toEqual(['/termos', '/privacidade']);
  });

  it('aceitar grava o aceite e tira a pendência da sessão', () => {
    botao('Aceitar').click();

    const pedido = httpMock.expectOne(`${API}/conta/aceitar-termos`);
    expect(pedido.request.method).toBe('POST');
    pedido.flush(null, { status: 204, statusText: 'No Content' });

    expect(auth.usuario()?.termos_pendentes).toBe(false);
  });

  it('erro ao aceitar mantém a pendência e mostra a mensagem', () => {
    botao('Aceitar').click();
    httpMock
      .expectOne(`${API}/conta/aceitar-termos`)
      .flush({ detail: 'falhou' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(auth.usuario()?.termos_pendentes).toBe(true);
    expect(fixture.nativeElement.querySelector('[role="alert"]')).not.toBeNull();
  });

  it('recusar encerra a sessão e leva ao login', () => {
    botao('Recusar').click();

    httpMock.expectOne(`${API}/auth/logout`).flush(null, { status: 204, statusText: 'No Content' });

    expect(auth.isAuthenticated()).toBe(false);
    expect(navegou).toEqual([['/login']]);
  });
});
