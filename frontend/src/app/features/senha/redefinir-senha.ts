import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { SENHA_MINIMA, senhasConferem } from '../../core/auth/senha';
import { mensagemDeErro } from '../../core/http/api-error';
import { Vitrine } from '../acesso/vitrine';

/**
 * Nova senha pelo link do e-mail (`/redefinir-senha?token=...`).
 * Consome `POST /api/v1/auth/redefinir-senha`.
 *
 * Depois de redefinir, todas as sessões abertas da conta caem (o backend revoga
 * os refresh tokens): a pessoa entra de novo com a senha nova.
 */
@Component({
  selector: 'app-redefinir-senha',
  imports: [ReactiveFormsModule, RouterLink, Vitrine],
  templateUrl: './redefinir-senha.html',
  styleUrl: '../acesso/acesso.css',
})
export class RedefinirSenha {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);

  protected readonly senhaMinima = SENHA_MINIMA;
  protected readonly token = inject(ActivatedRoute).snapshot.queryParamMap.get('token');
  protected readonly enviando = signal(false);
  protected readonly concluido = signal(false);
  protected readonly erro = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group(
    {
      nova_senha: ['', [Validators.required, Validators.minLength(SENHA_MINIMA)]],
      confirmacao: ['', [Validators.required]],
    },
    { validators: senhasConferem('nova_senha') },
  );

  protected enviar(): void {
    if (!this.token) {
      return;
    }
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.enviando.set(true);
    this.erro.set(null);

    this.auth.redefinirSenha(this.token, this.form.getRawValue().nova_senha).subscribe({
      next: () => {
        this.enviando.set(false);
        this.concluido.set(true);
        // Uma sessão antiga nesta aba já foi revogada no servidor: some com ela.
        this.auth.clearSession();
      },
      error: (erro: unknown) => {
        this.enviando.set(false);
        this.erro.set(mensagemDeErro(erro, 'Não foi possível redefinir a senha. Tente de novo.'));
      },
    });
  }

  protected invalido(campo: 'nova_senha' | 'confirmacao'): boolean {
    const controle = this.form.controls[campo];
    return controle.invalid && controle.touched;
  }

  protected senhasDiferentes(): boolean {
    const confirmacao = this.form.controls.confirmacao;
    return confirmacao.valid && confirmacao.touched && this.form.hasError('senhasDiferentes');
  }
}
