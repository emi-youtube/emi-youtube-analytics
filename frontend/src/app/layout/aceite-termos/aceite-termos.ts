import { Component, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { mensagemDeErro } from '../../core/http/api-error';

/**
 * Aceite pendente dos termos (ADR-012): quem tinha conta antes do aceite, ou
 * antes de uma versão nova, aceita aqui para continuar.
 *
 * Bloqueante: o `Shell` torna o resto da tela `inert` enquanto este modal está
 * aberto, e não há como fechá-lo sem escolher. Recusar encerra a sessão — usar o
 * sistema sem aceitar os termos vigentes não é uma opção.
 */
@Component({
  selector: 'app-aceite-termos',
  imports: [RouterLink],
  templateUrl: './aceite-termos.html',
  styleUrl: './aceite-termos.css',
})
export class AceiteTermos {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly enviando = signal(false);
  protected readonly erro = signal<string | null>(null);

  protected aceitar(): void {
    this.enviando.set(true);
    this.erro.set(null);
    this.auth.aceitarTermos().subscribe({
      // O modal some sozinho: `termos_pendentes` vira falso no usuário da sessão.
      next: () => this.enviando.set(false),
      error: (erro: unknown) => {
        this.enviando.set(false);
        this.erro.set(mensagemDeErro(erro, 'Não foi possível registrar o aceite. Tente de novo.'));
      },
    });
  }

  protected recusar(): void {
    this.auth.logout().subscribe({
      next: () => void this.router.navigate(['/login']),
      error: () => void this.router.navigate(['/login']),
    });
  }
}
