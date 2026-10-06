import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { EsqueciSenha } from './esqueci-senha';

const AUTH = `${environment.apiBaseUrl}/auth`;

describe('EsqueciSenha', () => {
  let fixture: ComponentFixture<EsqueciSenha>;
  let httpMock: HttpTestingController;

  function componente(): {
    form: EsqueciSenha['form'];
    enviado: EsqueciSenha['enviado'];
    erro: EsqueciSenha['erro'];
    enviar: () => void;
  } {
    return fixture.componentInstance as unknown as ReturnType<typeof componente>;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(EsqueciSenha);
  });

  afterEach(() => httpMock.verify());

  it('não envia e-mail inválido', () => {
    componente().form.setValue({ email: 'nao-e-email' });

    componente().enviar();

    httpMock.expectNone(`${AUTH}/esqueci-senha`);
  });

  it('envia o pedido e mostra a confirmação neutra', () => {
    componente().form.setValue({ email: 'marina@empresa.com.br' });

    componente().enviar();

    const pedido = httpMock.expectOne(`${AUTH}/esqueci-senha`);
    expect(pedido.request.body).toEqual({ email: 'marina@empresa.com.br' });
    pedido.flush(
      { detail: 'Se houver uma conta com este e-mail, enviaremos um link.' },
      { status: 202, statusText: 'Accepted' },
    );

    expect(componente().enviado()).toBe(true);
    fixture.detectChanges();
    // A frase não afirma que a conta existe.
    expect(fixture.nativeElement.textContent).toContain('Se houver uma conta com este e-mail');
  });

  it('traduz o 429 do limite por IP', () => {
    componente().form.setValue({ email: 'marina@empresa.com.br' });

    componente().enviar();

    httpMock
      .expectOne(`${AUTH}/esqueci-senha`)
      .flush({ detail: 'Muitos pedidos.' }, { status: 429, statusText: 'Too Many Requests' });

    expect(componente().enviado()).toBe(false);
    expect(componente().erro()).toContain('Muitos pedidos seguidos');
  });
});
