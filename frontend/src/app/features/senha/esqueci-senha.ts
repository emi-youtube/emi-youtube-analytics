import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';
import { Vitrine } from '../acesso/vitrine';

/**
 * Pedido de redefinição de senha. Consome `POST /api/v1/auth/esqueci-senha`.
 *
 * A confirmação é a MESMA exista ou não a conta — o backend responde 202 igual
 * nos dois casos, e a tela não pode desfazer isso dizendo "e-mail não
 * encontrado".
 */
@Component({
  selector: 'app-esqueci-senha',
  imports: [ReactiveFormsModule, RouterLink, Vitrine],
  templateUrl: './esqueci-senha.html',
  styleUrl: '../acesso/acesso.css',
})
export class EsqueciSenha {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);

  protected readonly enviando = signal(false);
  protected readonly enviado = signal(false);
  protected readonly erro = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email, Validators.maxLength(255)]],
  });

  protected enviar(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.enviando.set(true);
    this.erro.set(null);

    this.auth.esqueciSenha(this.form.getRawValue().email.trim()).subscribe({
      next: () => {
        this.enviando.set(false);
        this.enviado.set(true);
      },
      error: (erro: unknown) => {
        this.enviando.set(false);
        this.erro.set(
          statusDoErro(erro) === 429
            ? 'Muitos pedidos seguidos. Aguarde alguns minutos e tente de novo.'
            : mensagemDeErro(erro, 'Não foi possível enviar o pedido. Tente de novo.'),
        );
      },
    });
  }

  protected invalido(): boolean {
    const controle = this.form.controls.email;
    return controle.invalid && controle.touched;
  }
}
