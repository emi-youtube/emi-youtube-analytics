import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth/auth.service';
import { Shell } from './shell';

const AUTH = `${environment.apiBaseUrl}/auth`;

describe('Shell', () => {
  let httpMock: HttpTestingController;

  function montar(termosPendentes: boolean): HTMLElement {
    TestBed.inject(AuthService).login({ email: 'a@b.com', senha: 'x' }).subscribe();
    httpMock
      .expectOne(`${AUTH}/login`)
      .flush({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    httpMock.expectOne(`${AUTH}/eu`).flush({
      id_usuario: 1,
      nome: 'Marina Rocha',
      email: 'a@b.com',
      papel: 'usuario_pme',
      papel_empresa: 'dono',
      empresa: { id_empresa: 1, nome: 'Loja' },
      criado_em: '2026-09-20T00:00:00',
      termos_pendentes: termosPendentes,
    });
    const fixture = TestBed.createComponent(Shell);
    fixture.detectChanges();
    return fixture.nativeElement;
  }

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('termos pendentes: abre o modal e deixa o resto da tela inerte', () => {
    const tela = montar(true);

    expect(tela.querySelector('app-aceite-termos')).not.toBeNull();
    expect(tela.querySelector('.shell')?.hasAttribute('inert')).toBe(true);
  });

  it('sem pendência: sem modal, e com os links legais no pé da nav', () => {
    const tela = montar(false);

    expect(tela.querySelector('app-aceite-termos')).toBeNull();
    expect(tela.querySelector('.shell')?.hasAttribute('inert')).toBe(false);
    const links = Array.from(tela.querySelectorAll('.legal a')).map((a) => a.getAttribute('href'));
    expect(links).toEqual(['/termos', '/privacidade']);
  });
});
