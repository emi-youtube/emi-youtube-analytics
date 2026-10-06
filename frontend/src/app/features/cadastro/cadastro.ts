import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ConviteParaCadastro, RegisterRequest } from '../../core/auth/auth.models';
import { AuthService, ContaCriadaSemSessao } from '../../core/auth/auth.service';
import { SENHA_MINIMA, senhasConferem } from '../../core/auth/senha';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';
import { Vitrine } from '../acesso/vitrine';

/**
 * Aceita o link inteiro (`.../entrar?convite=abc`) ou só o código. Quem recebe o
 * convite por outro canal costuma colar o link todo.
 */
export function tokenDoConvite(texto: string): string {
  const limpo = texto.trim();
  const marcador = limpo.match(/[?&]convite=([^&#\s]+)/);
  return marcador ? decodeURIComponent(marcador[1]) : limpo;
}

type Modo = 'criar' | 'convite';

/**
 * UC02 — criação de conta. Consome `POST /api/v1/auth/registrar`.
 *
 * Dois caminhos (ADR-011): "Criar empresa" faz da pessoa a dona de uma empresa
 * nova; "Tenho um convite" a põe na empresa de quem convidou, com o e-mail do
 * convite travado — o backend recusa qualquer outro.
 */
@Component({
  selector: 'app-cadastro',
  imports: [ReactiveFormsModule, RouterLink, Vitrine],
  templateUrl: './cadastro.html',
  styleUrls: ['../acesso/acesso.css', './cadastro.css'],
})
export class Cadastro {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly senhaMinima = SENHA_MINIMA;
  protected readonly modo = signal<Modo>('criar');
  protected readonly enviando = signal(false);
  protected readonly erro = signal<string | null>(null);
  /** Trava o botão depois de `ContaCriadaSemSessao`: reenviar daria 409. */
  protected readonly contaCriada = signal(false);

  /** Convite já validado no servidor; enquanto nulo, o modo convite pede o código. */
  protected readonly convite = signal<ConviteParaCadastro | null>(null);
  protected readonly consultandoConvite = signal(false);
  private tokenConvite: string | null = null;

  protected readonly codigoConvite = this.fb.nonNullable.control('', Validators.required);

  protected readonly form = this.fb.nonNullable.group(
    {
      nome: ['', [Validators.required, Validators.maxLength(255)]],
      email: ['', [Validators.required, Validators.email, Validators.maxLength(255)]],
      nome_empresa: ['', [Validators.required, Validators.maxLength(120)]],
      senha: ['', [Validators.required, Validators.minLength(SENHA_MINIMA)]],
      confirmacao: ['', [Validators.required]],
      // ADR-012: sem o aceite o botão fica desabilitado e o backend responde 422.
      aceite_termos: [false, [Validators.requiredTrue]],
    },
    { validators: senhasConferem() },
  );

  constructor() {
    const token = this.route.snapshot.queryParamMap.get('convite');
    if (token) {
      this.escolher('convite');
      // No SSR não há por que consultar: a tela hidrata e consulta no navegador.
      if (this.isBrowser) {
        this.validarConvite(token);
      }
    }
  }

  protected escolher(modo: Modo): void {
    this.modo.set(modo);
    this.erro.set(null);
    const nomeEmpresa = this.form.controls.nome_empresa;
    if (modo === 'criar') {
      nomeEmpresa.enable();
      this.convite.set(null);
      this.tokenConvite = null;
      this.form.controls.email.enable();
    } else {
      // Fora da validação: a empresa vem do convite, não de quem preenche.
      nomeEmpresa.disable();
    }
  }

  protected validarCodigo(): void {
    if (this.codigoConvite.invalid) {
      this.codigoConvite.markAsTouched();
      return;
    }
    this.validarConvite(tokenDoConvite(this.codigoConvite.value));
  }

  private validarConvite(token: string): void {
    this.consultandoConvite.set(true);
    this.erro.set(null);

    this.auth.consultarConvite(token).subscribe({
      next: (convite) => {
        this.consultandoConvite.set(false);
        this.tokenConvite = token;
        this.convite.set(convite);
        // E-mail travado: o backend compara com o do convite e recusaria outro.
        this.form.controls.email.setValue(convite.email);
        this.form.controls.email.disable();
      },
      error: (erro: unknown) => {
        this.consultandoConvite.set(false);
        this.erro.set(
          statusDoErro(erro) === 404
            ? 'Este convite é inválido, já foi usado ou expirou. Peça um novo a quem convidou.'
            : mensagemDeErro(erro, 'Não foi possível validar o convite. Tente de novo.'),
        );
      },
    });
  }

  protected enviar(): void {
    if (this.modo() === 'convite' && !this.convite()) {
      this.validarCodigo();
      return;
    }
    if (this.form.invalid || this.contaCriada()) {
      this.form.markAllAsTouched();
      return;
    }

    const { nome, email, nome_empresa, senha } = this.form.getRawValue();
    const dados: RegisterRequest = {
      nome: nome.trim(),
      email: email.trim(),
      senha,
      aceite_termos: true,
    };
    if (this.modo() === 'convite' && this.tokenConvite) {
      dados.token_convite = this.tokenConvite;
    } else {
      dados.nome_empresa = nome_empresa.trim();
    }

    this.enviando.set(true);
    this.erro.set(null);

    this.auth.registrar(dados).subscribe({
      next: () => {
        void this.router.navigateByUrl('/inicio');
      },
      error: (erro: unknown) => {
        this.enviando.set(false);

        if (erro instanceof ContaCriadaSemSessao) {
          this.contaCriada.set(true);
          this.erro.set(
            'Sua conta foi criada, mas não foi possível entrar automaticamente. ' +
              'Use a tela de entrada.',
          );
          return;
        }

        this.erro.set(this.mensagemDoCadastro(erro));
      },
    });
  }

  /**
   * O 409 de e-mail repetido tem uma saída melhor do que "tente de novo"; o 409
   * de empresa lotada e o 400 de convite inválido já vêm com texto próprio do
   * backend e vão pelo tradutor comum.
   */
  private mensagemDoCadastro(erro: unknown): string {
    const detalhe = mensagemDeErro(erro, 'Não foi possível criar sua conta. Tente de novo.');
    if (statusDoErro(erro) === 409 && detalhe.includes('e-mail')) {
      return 'Já existe uma conta com este e-mail. Entre com ela ou use outro endereço.';
    }
    return detalhe;
  }

  protected invalido(campo: 'nome' | 'email' | 'nome_empresa' | 'senha' | 'confirmacao'): boolean {
    const controle = this.form.controls[campo];
    return controle.invalid && controle.touched;
  }

  /** Confirmação preenchida, válida por si só, mas diferente da senha. */
  protected senhasDiferentes(): boolean {
    const confirmacao = this.form.controls.confirmacao;
    return confirmacao.valid && confirmacao.touched && this.form.hasError('senhasDiferentes');
  }
}
