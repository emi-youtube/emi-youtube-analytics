import { Component, inject, signal } from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService, ContaCriadaSemSessao } from '../../core/auth/auth.service';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';
import { Vitrine } from '../acesso/vitrine';

/** Mesmo mínimo de `SENHA_MIN_CARACTERES` em `backend/app/schemas/auth.py`. */
const SENHA_MINIMA = 8;

/**
 * Valida a confirmação contra a senha.
 *
 * Fica no grupo, e não no campo, porque depende de dois controles: um
 * validador de campo não enxerga o irmão.
 */
function senhasConferem(grupo: AbstractControl): ValidationErrors | null {
  const senha = grupo.get('senha')?.value;
  const confirmacao = grupo.get('confirmacao')?.value;

  // Com a confirmação ainda vazia o erro é "obrigatório", não "diferente" —
  // acusar divergência enquanto a pessoa digita seria só ruído.
  if (!confirmacao || senha === confirmacao) {
    return null;
  }
  return { senhasDiferentes: true };
}

/** UC02 — criação de conta. Consome `POST /api/v1/auth/registrar`. */
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

  protected readonly senhaMinima = SENHA_MINIMA;
  protected readonly enviando = signal(false);
  protected readonly erro = signal<string | null>(null);
  /** Trava o botão depois de `ContaCriadaSemSessao`: reenviar daria 409. */
  protected readonly contaCriada = signal(false);

  protected readonly form = this.fb.nonNullable.group(
    {
      nome: ['', [Validators.required, Validators.maxLength(255)]],
      email: ['', [Validators.required, Validators.email, Validators.maxLength(255)]],
      senha: ['', [Validators.required, Validators.minLength(SENHA_MINIMA)]],
      confirmacao: ['', [Validators.required]],
    },
    { validators: senhasConferem },
  );

  protected enviar(): void {
    if (this.form.invalid || this.contaCriada()) {
      this.form.markAllAsTouched();
      return;
    }

    const { nome, email, senha } = this.form.getRawValue();

    this.enviando.set(true);
    this.erro.set(null);

    this.auth.registrar({ nome: nome.trim(), email: email.trim(), senha }).subscribe({
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
   * O 409 é o único caso em que o usuário tem uma saída melhor do que "tente
   * de novo", então ganha texto próprio; o resto vai pelo tradutor comum.
   */
  private mensagemDoCadastro(erro: unknown): string {
    if (statusDoErro(erro) === 409) {
      return 'Já existe uma conta com este e-mail. Entre com ela ou use outro endereço.';
    }
    return mensagemDeErro(erro, 'Não foi possível criar sua conta. Tente de novo.');
  }

  protected invalido(campo: 'nome' | 'email' | 'senha' | 'confirmacao'): boolean {
    const controle = this.form.controls[campo];
    return controle.invalid && controle.touched;
  }

  /** Confirmação preenchida, válida por si só, mas diferente da senha. */
  protected senhasDiferentes(): boolean {
    const confirmacao = this.form.controls.confirmacao;
    return confirmacao.valid && confirmacao.touched && this.form.hasError('senhasDiferentes');
  }
}
