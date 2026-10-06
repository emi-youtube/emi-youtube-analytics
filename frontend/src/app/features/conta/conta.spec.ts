import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth/auth.service';
import { Conta } from './conta';

const AUTH = `${environment.apiBaseUrl}/auth`;
const CONTA = `${environment.apiBaseUrl}/conta`;

describe('Conta', () => {
  let fixture: ComponentFixture<Conta>;
  let httpMock: HttpTestingController;
  let navegou: unknown[];

  function componente(): {
    form: Conta['form'];
    sucesso: Conta['sucesso'];
    erro: Conta['erro'];
    trocar: () => void;
    exclusao: Conta['exclusao'];
    erroExclusao: Conta['erroExclusao'];
    excluirConta: () => void;
    baixarDados: () => void;
  } {
    return fixture.componentInstance as unknown as ReturnType<typeof componente>;
  }

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    navegou = [];
    vi.spyOn(TestBed.inject(Router), 'navigate').mockImplementation((destino) => {
      navegou.push(destino);
      return Promise.resolve(true);
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

  /** Sessão aberta como `papel_empresa`; a zona de perigo depende dele. */
  function entrar(papel_empresa: 'dono' | 'membro'): void {
    TestBed.inject(AuthService).login({ email: 'a@b.com', senha: 'x' }).subscribe();
    httpMock
      .expectOne(`${AUTH}/login`)
      .flush({ access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer' });
    httpMock.expectOne(`${AUTH}/eu`).flush({
      id_usuario: 1,
      nome: 'Marina',
      email: 'a@b.com',
      papel: 'usuario_pme',
      papel_empresa,
      empresa: { id_empresa: 1, nome: 'Loja da Marina' },
      criado_em: '2026-09-20T00:00:00',
      termos_pendentes: false,
    });
    fixture.detectChanges();
  }

  function textoDoPerigo(): string {
    return fixture.nativeElement.querySelector('[data-testid="perigo-texto"]').textContent;
  }

  it('dono: avisa que a empresa inteira será apagada', () => {
    entrar('dono');

    expect(textoDoPerigo()).toContain('empresa inteira');
    expect(textoDoPerigo()).toContain('Loja da Marina');
  });

  it('membro: avisa que os modelos passam ao dono e as análises ficam', () => {
    entrar('membro');

    expect(textoDoPerigo()).toContain('passam para o');
    expect(textoDoPerigo()).not.toContain('empresa inteira');
  });

  it('baixar meus dados busca o JSON e oferece o arquivo', () => {
    entrar('membro');
    const criar = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    componente().baixarDados();
    httpMock.expectOne(`${CONTA}/meus-dados`).flush({ email: 'a@b.com' });

    expect(criar).toHaveBeenCalled();
    expect(clique).toHaveBeenCalled();
  });

  it('não exclui sem a senha', () => {
    entrar('membro');

    componente().excluirConta();

    httpMock.expectNone(`${AUTH}/refresh`);
    httpMock.expectNone(CONTA);
  });

  it('exclui: renova a sessão, envia a senha, encerra a sessão e vai ao login', () => {
    entrar('membro');
    componente().exclusao.setValue({ senha: 'SenhaForte123' });

    componente().excluirConta();

    httpMock
      .expectOne(`${AUTH}/refresh`)
      .flush({ access_token: 'access-2', refresh_token: 'refresh-2', token_type: 'bearer' });
    const pedido = httpMock.expectOne(CONTA);
    expect(pedido.request.method).toBe('DELETE');
    expect(pedido.request.body).toEqual({ senha: 'SenhaForte123' });
    pedido.flush(null, { status: 204, statusText: 'No Content' });

    expect(TestBed.inject(AuthService).isAuthenticated()).toBe(false);
    expect(localStorage.getItem('emi.refresh_token')).toBeNull();
    expect(navegou).toEqual([['/login']]);
  });

  it('senha errada: mostra "Senha incorreta." e mantém a sessão', () => {
    entrar('membro');
    componente().exclusao.setValue({ senha: 'errada-123' });

    componente().excluirConta();
    httpMock
      .expectOne(`${AUTH}/refresh`)
      .flush({ access_token: 'access-2', refresh_token: 'refresh-2', token_type: 'bearer' });
    httpMock
      .expectOne(CONTA)
      .flush({ detail: 'Senha incorreta.' }, { status: 401, statusText: 'Unauthorized' });

    expect(componente().erroExclusao()).toBe('Senha incorreta.');
    expect(TestBed.inject(AuthService).isAuthenticated()).toBe(true);
    expect(navegou).toEqual([]);
  });

  it('dono com membros: mostra a recusa do backend', () => {
    entrar('dono');
    componente().exclusao.setValue({ senha: 'SenhaForte123' });

    componente().excluirConta();
    httpMock
      .expectOne(`${AUTH}/refresh`)
      .flush({ access_token: 'access-2', refresh_token: 'refresh-2', token_type: 'bearer' });
    httpMock
      .expectOne(CONTA)
      .flush(
        { detail: 'Você é dono de uma empresa com outros membros.' },
        { status: 409, statusText: 'Conflict' },
      );

    expect(componente().erroExclusao()).toContain('outros membros');
  });
});
