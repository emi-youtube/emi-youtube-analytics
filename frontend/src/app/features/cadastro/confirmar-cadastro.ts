import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';
import { Vitrine } from '../acesso/vitrine';

/**
 * Link do e-mail de confirmação (`/confirmar-cadastro?token=...`, ADR-014).
 * Consome `POST /api/v1/auth/confirmar-cadastro`, que cria a empresa e a conta
 * de dono e já devolve a sessão: deu certo, vai direto para o início.
 *
 * Confirma sozinha ao abrir, sem botão: o link é de uso único e quem o abriu
 * acabou de recebê-lo. No SSR não confirma; a tela hidrata e confirma no navegador.
 */
@Component({
  selector: 'app-confirmar-cadastro',
  imports: [RouterLink, Vitrine],
  templateUrl: './confirmar-cadastro.html',
  styleUrl: '../acesso/acesso.css',
})
export class ConfirmarCadastro {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly token = inject(ActivatedRoute).snapshot.queryParamMap.get('token');
  protected readonly erro = signal<string | null>(null);

  constructor() {
    if (!this.token) {
      this.erro.set('Este link está incompleto. Abra de novo o link do e-mail.');
      return;
    }
    if (isPlatformBrowser(inject(PLATFORM_ID))) {
      this.confirmar(this.token);
    }
  }

  private confirmar(token: string): void {
    this.auth.confirmarCadastro(token).subscribe({
      next: () => {
        void this.router.navigateByUrl('/inicio');
      },
      error: (erro: unknown) => {
        this.erro.set(
          statusDoErro(erro) === 409
            ? 'Este e-mail já tem conta. Entre com ela.'
            : mensagemDeErro(erro, 'Não foi possível confirmar o cadastro. Tente de novo.'),
        );
      },
    });
  }
}
