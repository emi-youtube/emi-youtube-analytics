import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { AuthService } from '../../core/auth/auth.service';
import { SENHA_MINIMA, senhasConferem } from '../../core/auth/senha';
import { mensagemDeErro } from '../../core/http/api-error';

/**
 * Minha conta: dados de quem está logado e troca de senha.
 * Consome `POST /api/v1/auth/trocar-senha`.
 */
@Component({
  selector: 'app-conta',
  imports: [ReactiveFormsModule],
  templateUrl: './conta.html',
  styleUrls: ['../painel/painel.css', './conta.css'],
})
export class Conta {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);

  protected readonly usuario = this.auth.usuario;
  protected readonly senhaMinima = SENHA_MINIMA;
  protected readonly enviando = signal(false);
  protected readonly sucesso = signal(false);
  protected readonly erro = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group(
    {
      senha_atual: ['', [Validators.required]],
      nova_senha: ['', [Validators.required, Validators.minLength(SENHA_MINIMA)]],
      confirmacao: ['', [Validators.required]],
    },
    { validators: senhasConferem('nova_senha') },
  );

  protected trocar(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { senha_atual, nova_senha } = this.form.getRawValue();
    this.enviando.set(true);
    this.erro.set(null);
    this.sucesso.set(false);

    this.auth.trocarSenha({ senha_atual, nova_senha }).subscribe({
      next: () => {
        this.enviando.set(false);
        this.sucesso.set(true);
        this.form.reset();
      },
      error: (erro: unknown) => {
        this.enviando.set(false);
        this.erro.set(mensagemDeErro(erro, 'Não foi possível trocar a senha. Tente de novo.'));
      },
    });
  }

  protected invalido(campo: 'senha_atual' | 'nova_senha' | 'confirmacao'): boolean {
    const controle = this.form.controls[campo];
    return controle.invalid && controle.touched;
  }

  protected senhasDiferentes(): boolean {
    const confirmacao = this.form.controls.confirmacao;
    return confirmacao.valid && confirmacao.touched && this.form.hasError('senhasDiferentes');
  }
}
