import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { mensagemDeErro } from '../../core/http/api-error';
import { Vitrine } from '../acesso/vitrine';

/** UC01 — autenticação. Consome `POST /api/v1/auth/login`. */
@Component({
  selector: 'app-login',
  imports: [ReactiveFormsModule, RouterLink, Vitrine],
  templateUrl: './login.html',
  // Layout e formulário são compartilhados com o cadastro (UC02).
  styleUrl: '../acesso/acesso.css',
})
export class Login {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly enviando = signal(false);
  protected readonly erro = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    // O mínimo de 8 caracteres é validado no servidor no cadastro; aqui só
    // exigimos preenchimento, senão uma senha antiga mais curta nem sairia da tela.
    senha: ['', [Validators.required]],
  });

  protected enviar(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.enviando.set(true);
    this.erro.set(null);

    this.auth.login(this.form.getRawValue()).subscribe({
      next: () => {
        // `returnUrl` é posto pelo authGuard quando a sessão expira no meio do uso.
        const destino = this.route.snapshot.queryParamMap.get('returnUrl') ?? '/inicio';
        void this.router.navigateByUrl(destino);
      },
      error: (erro: unknown) => {
        this.enviando.set(false);
        this.erro.set(mensagemDeErro(erro, 'Não foi possível entrar. Tente de novo.'));
      },
    });
  }

  protected invalido(campo: 'email' | 'senha'): boolean {
    const controle = this.form.controls[campo];
    return controle.invalid && controle.touched;
  }
}
