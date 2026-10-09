import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { Cadastro, tokenDoConvite } from './cadastro';

const AUTH = `${environment.apiBaseUrl}/auth`;

const USUARIO = {
  id_usuario: 7,
  nome: 'Marina Rocha',
  email: 'marina@empresa.com.br',
  papel: 'usuario_pme',
  papel_empresa: 'dono',
  empresa: { id_empresa: 3, nome: 'Loja da Marina' },
  criado_em: '2026-09-21T00:00:00',
};

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
    convite: Cadastro['convite'];
    modo: Cadastro['modo'];
    codigoConvite: Cadastro['codigoConvite'];
    enviar: () => void;
    escolher: (modo: 'criar' | 'convite') => void;
    validarCodigo: () => void;
  } {
    return fixture.componentInstance as unknown as ReturnType<typeof componente>;
  }

  /** Monta a tela; `convite` simula o link `/entrar?convite=...`. */
  function montar(convite?: string): void {
    localStorage.clear();
    navegou = [];

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { queryParamMap: convertToParamMap(convite ? { convite } : {}) },
          },
        },
      ],
    });

    vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockImplementation((destino) => {
      navegou.push(destino.toString());
      return Promise.resolve(true);
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Cadastro);
  }

  function preencher(senha = 'senha-forte-1', confirmacao = senha, aceite = true): void {
    const form = componente().form;
    form.controls.nome.setValue('Marina Rocha');
    if (form.controls.email.enabled) {
      form.controls.email.setValue('marina@empresa.com.br');
    }
    form.controls.nome_empresa.setValue('Loja da Marina');
    form.controls.senha.setValue(senha);
    form.controls.confirmacao.setValue(confirmacao);
    form.controls.aceite_termos.setValue(aceite);
  }

  /** Fecha o login automático que segue o cadastro. */
  function concluirLogin(): void {
    httpMock
      .expectOne(`${AUTH}/login`)
      .flush({ access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer' });
    httpMock.expectOne(`${AUTH}/eu`).flush(USUARIO);
  }

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('não envia quando a confirmação difere da senha', () => {
    montar();
    preencher('senha-forte-1', 'senha-forte-2');

    componente().enviar();

    httpMock.expectNone(`${AUTH}/registrar`);
  });

  it('sem o aceite dos termos não envia e o botão fica desabilitado', () => {
    montar();
    preencher('senha-forte-1', 'senha-forte-1', false);
    fixture.detectChanges();

    const botao: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(botao.disabled).toBe(true);
    componente().enviar();
    httpMock.expectNone(`${AUTH}/registrar`);

    componente().form.controls.aceite_termos.setValue(true);
    fixture.detectChanges();
    expect(botao.disabled).toBe(false);
  });

  it('o aceite traz links para os Termos e a Política', () => {
    montar();
    fixture.detectChanges();

    const links = Array.from(
      fixture.nativeElement.querySelectorAll('.aceite a') as NodeListOf<HTMLAnchorElement>,
    ).map((a) => a.getAttribute('href'));
    expect(links).toEqual(['/termos', '/privacidade']);
  });

  it('criar empresa: exige o nome da empresa', () => {
    montar();
    preencher();
    componente().form.controls.nome_empresa.setValue('');

    componente().enviar();

    httpMock.expectNone(`${AUTH}/registrar`);
  });

  it('criar empresa: pede o cadastro e manda confirmar pelo e-mail, sem entrar', () => {
    montar();
    preencher();

    componente().enviar();

    const registro = httpMock.expectOne(`${AUTH}/registrar`);
    expect(registro.request.body).toEqual({
      nome: 'Marina Rocha',
      email: 'marina@empresa.com.br',
      senha: 'senha-forte-1',
      nome_empresa: 'Loja da Marina',
      aceite_termos: true,
    });
    registro.flush(
      { detail: 'Enviamos um link para o seu e-mail.' },
      { status: 202, statusText: 'Accepted' },
    );
    fixture.detectChanges();

    // ADR-014: nada de login automático; a conta nasce no link do e-mail.
    httpMock.expectNone(`${AUTH}/login`);
    expect(navegou).toEqual([]);
    const aviso = fixture.nativeElement.querySelector('[data-testid="cadastro-enviado"]');
    expect(aviso.textContent).toContain('marina@empresa.com.br');
    expect(fixture.nativeElement.querySelector('form input#senha')).toBeNull();
  });

  it('convite pelo link: consulta, trava o e-mail e registra com o token', () => {
    montar('tok-123');

    expect(componente().modo()).toBe('convite');
    const consulta = httpMock.expectOne(`${AUTH}/convites/consultar`);
    expect(consulta.request.body).toEqual({ token: 'tok-123' });
    consulta.flush({
      email: 'convidada@empresa.com.br',
      nome_empresa: 'Loja da Marina',
      papel_empresa: 'membro',
    });

    const email = componente().form.controls.email;
    expect(email.value).toBe('convidada@empresa.com.br');
    expect(email.disabled).toBe(true);

    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Loja da Marina');

    preencher();
    componente().enviar();

    const registro = httpMock.expectOne(`${AUTH}/registrar`);
    // Sem nome_empresa: quem entra por convite não cria empresa.
    expect(registro.request.body).toEqual({
      nome: 'Marina Rocha',
      email: 'convidada@empresa.com.br',
      senha: 'senha-forte-1',
      token_convite: 'tok-123',
      aceite_termos: true,
    });
    registro.flush(USUARIO, { status: 201, statusText: 'Created' });
    concluirLogin();
    expect(navegou).toEqual(['/inicio']);
  });

  it('convite inválido mostra o erro e não libera o formulário', () => {
    montar('tok-velho');

    httpMock
      .expectOne(`${AUTH}/convites/consultar`)
      .flush({ detail: 'Convite inválido ou expirado.' }, { status: 404, statusText: 'Not Found' });

    expect(componente().convite()).toBeNull();
    expect(componente().erro()).toContain('inválido');

    componente().enviar();
    // Sem convite validado o envio só tenta validar o código (vazio), não registra.
    httpMock.expectNone(`${AUTH}/registrar`);
  });

  it('"Tenho um convite" aceita o link colado inteiro', () => {
    montar();
    componente().escolher('convite');
    componente().codigoConvite.setValue('https://emi.app/entrar?convite=abc%2D1&x=2');

    componente().validarCodigo();

    const consulta = httpMock.expectOne(`${AUTH}/convites/consultar`);
    expect(consulta.request.body).toEqual({ token: 'abc-1' });
    consulta.flush({ email: 'a@b.com', nome_empresa: 'X', papel_empresa: 'membro' });
  });

  it('tokenDoConvite aceita só o código também', () => {
    expect(tokenDoConvite('  abc  ')).toBe('abc');
  });

  it('por convite, traduz o 409 de e-mail já cadastrado', () => {
    montar('tok-123');
    httpMock
      .expectOne(`${AUTH}/convites/consultar`)
      .flush({ email: 'c@empresa.com.br', nome_empresa: 'Loja', papel_empresa: 'membro' });
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

  it('mostra o 409 de empresa lotada como veio do servidor', () => {
    montar('tok-123');
    httpMock
      .expectOne(`${AUTH}/convites/consultar`)
      .flush({ email: 'c@empresa.com.br', nome_empresa: 'Loja', papel_empresa: 'membro' });
    preencher();

    componente().enviar();

    httpMock
      .expectOne(`${AUTH}/registrar`)
      .flush(
        { detail: 'A empresa atingiu o limite de membros.' },
        { status: 409, statusText: 'Conflict' },
      );

    expect(componente().erro()).toBe('A empresa atingiu o limite de membros.');
  });

  it('por convite, avisa que a conta existe quando só o login automático falha', () => {
    montar('tok-123');
    httpMock
      .expectOne(`${AUTH}/convites/consultar`)
      .flush({ email: 'c@empresa.com.br', nome_empresa: 'Loja', papel_empresa: 'membro' });
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
