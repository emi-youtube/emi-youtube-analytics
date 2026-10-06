import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { environment } from '../../../environments/environment';
import { PapelEmpresa } from '../../core/auth/auth.models';
import { AuthService } from '../../core/auth/auth.service';
import { Empresa } from './empresa';

const API = environment.apiBaseUrl;

const MEMBROS = [
  {
    id_usuario: 1,
    nome: 'Marina Rocha',
    email: 'marina@empresa.com.br',
    papel_empresa: 'dono',
    criado_em: '2026-09-21T00:00:00',
  },
  {
    id_usuario: 2,
    nome: 'Caio Lima',
    email: 'caio@empresa.com.br',
    papel_empresa: 'membro',
    criado_em: '2026-09-22T00:00:00',
  },
];

describe('Empresa', () => {
  let fixture: ComponentFixture<Empresa>;
  let httpMock: HttpTestingController;

  function componente(): {
    form: Empresa['form'];
    criado: Empresa['criado'];
    membros: Empresa['membros'];
    convites: Empresa['convites'];
    convidar: () => void;
    remover: (m: (typeof MEMBROS)[number]) => void;
    alterarPapel: (m: (typeof MEMBROS)[number]) => void;
    erroAcao: Empresa['erroAcao'];
  } {
    return fixture.componentInstance as unknown as ReturnType<typeof componente>;
  }

  /** Monta a tela com a sessão de `papel` já carregada (o que o authGuard garante). */
  function montar(papel: PapelEmpresa, idUsuario = 1): void {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);

    const auth = TestBed.inject(AuthService);
    auth.loadCurrentUser().subscribe();
    httpMock.expectOne(`${API}/auth/eu`).flush({
      id_usuario: idUsuario,
      nome: 'Quem logou',
      email: 'x@empresa.com.br',
      papel: 'usuario_pme',
      papel_empresa: papel,
      empresa: { id_empresa: 3, nome: 'Loja da Marina' },
      criado_em: '2026-09-21T00:00:00',
    });

    fixture = TestBed.createComponent(Empresa);
    httpMock.expectOne(`${API}/empresa/membros`).flush(MEMBROS);
    if (papel === 'dono') {
      httpMock.expectOne(`${API}/empresa/convites`).flush([]);
    }
    fixture.detectChanges();
  }

  afterEach(() => httpMock.verify());

  it('mostra o nome da empresa e os membros', () => {
    montar('membro', 2);

    const texto = fixture.nativeElement.textContent as string;
    expect(texto).toContain('Loja da Marina');
    expect(texto).toContain('marina@empresa.com.br');
    expect(texto).toContain('caio@empresa.com.br');
  });

  it('membro não vê as ações nem busca convites', () => {
    montar('membro', 2);

    expect(fixture.nativeElement.querySelector('[data-testid="convidar"]')).toBeNull();
    const botoes = [...fixture.nativeElement.querySelectorAll('button')].map(
      (b: HTMLButtonElement) => b.textContent?.trim(),
    );
    expect(botoes).not.toContain('Remover');
    // O afterEach (verify) confirma que GET /empresa/convites não foi chamado.
  });

  it('dono gera convite e vê o link uma vez', () => {
    montar('dono');
    componente().form.setValue({ email: 'nova@empresa.com.br', papel_empresa: 'membro' });

    componente().convidar();

    const pedido = httpMock.expectOne(`${API}/empresa/convites`);
    expect(pedido.request.method).toBe('POST');
    expect(pedido.request.body).toEqual({ email: 'nova@empresa.com.br', papel_empresa: 'membro' });
    const criado = {
      id_convite: 9,
      email: 'nova@empresa.com.br',
      papel_empresa: 'membro',
      expira_em: '2026-10-13T00:00:00',
      criado_em: '2026-10-06T00:00:00',
      link: 'http://localhost:4200/entrar?convite=tok-9',
    };
    pedido.flush(criado, { status: 201, statusText: 'Created' });
    // Depois de criar, a lista de pendentes é recarregada — e não traz o link.
    const { link: _link, ...semLink } = criado;
    httpMock.expectOne(`${API}/empresa/convites`).flush([semLink]);
    fixture.detectChanges();

    const caixa = fixture.nativeElement.querySelector('[data-testid="link-convite"]');
    expect(caixa.querySelector('input').value).toBe(criado.link);
    expect(componente().convites()).toHaveLength(1);
  });

  it('dono não vê "Remover" na própria linha', () => {
    montar('dono', 1);

    const linhas = fixture.nativeElement.querySelectorAll('[data-testid="membros"] li');
    expect(linhas[0].textContent).not.toContain('Remover');
    expect(linhas[1].textContent).toContain('Remover');
  });

  it('remover pede confirmação antes de chamar a API', () => {
    montar('dono', 1);
    const caio = MEMBROS[1];

    componente().remover(caio);
    httpMock.expectNone(`${API}/empresa/membros/2`);

    componente().remover(caio);
    const pedido = httpMock.expectOne(`${API}/empresa/membros/2`);
    expect(pedido.request.method).toBe('DELETE');
    pedido.flush(null, { status: 204, statusText: 'No Content' });

    expect(
      componente()
        .membros()
        .map((m) => m.id_usuario),
    ).toEqual([1]);
  });

  function botoesDePapel(): HTMLButtonElement[] {
    return Array.from(
      fixture.nativeElement.querySelectorAll('[data-testid="alterar-papel"]'),
    ) as HTMLButtonElement[];
  }

  it('membro não vê as ações de papel', () => {
    montar('membro', 2);

    expect(botoesDePapel()).toHaveLength(0);
  });

  it('dono vê "Tirar de dono" para dono e "Tornar dono" para membro', () => {
    montar('dono');

    expect(botoesDePapel().map((b) => b.textContent?.trim())).toEqual([
      'Tirar de dono',
      'Tornar dono',
    ]);
  });

  it('tornar dono pede confirmação e atualiza o papel na lista', () => {
    montar('dono');

    componente().alterarPapel(MEMBROS[1]);
    httpMock.expectNone(`${API}/empresa/membros/2`);
    fixture.detectChanges();
    expect(botoesDePapel()[1].textContent).toContain('Confirmar');

    componente().alterarPapel(MEMBROS[1]);
    const pedido = httpMock.expectOne(`${API}/empresa/membros/2`);
    expect(pedido.request.method).toBe('PATCH');
    expect(pedido.request.body).toEqual({ papel_empresa: 'dono' });
    pedido.flush({ ...MEMBROS[1], papel_empresa: 'dono' });

    expect(componente().membros()[1].papel_empresa).toBe('dono');
  });

  it('rebaixar o último dono mostra a recusa do backend', () => {
    montar('dono');

    componente().alterarPapel(MEMBROS[0]);
    componente().alterarPapel(MEMBROS[0]);
    httpMock
      .expectOne(`${API}/empresa/membros/1`)
      .flush(
        { detail: 'A empresa precisa de ao menos um dono.' },
        { status: 409, statusText: 'Conflict' },
      );

    expect(componente().erroAcao()).toBe('A empresa precisa de ao menos um dono.');
    expect(componente().membros()[0].papel_empresa).toBe('dono');
  });

  it('rebaixar a si mesmo recarrega a sessão', () => {
    montar('dono');

    componente().alterarPapel(MEMBROS[0]);
    componente().alterarPapel(MEMBROS[0]);
    httpMock
      .expectOne(`${API}/empresa/membros/1`)
      .flush({ ...MEMBROS[0], papel_empresa: 'membro' });

    httpMock.expectOne(`${API}/auth/eu`).flush({
      id_usuario: 1,
      nome: 'Quem logou',
      email: 'x@empresa.com.br',
      papel: 'usuario_pme',
      papel_empresa: 'membro',
      empresa: { id_empresa: 3, nome: 'Loja da Marina' },
      criado_em: '2026-09-21T00:00:00',
    });
    fixture.detectChanges();
    expect(botoesDePapel()).toHaveLength(0);
  });
});
