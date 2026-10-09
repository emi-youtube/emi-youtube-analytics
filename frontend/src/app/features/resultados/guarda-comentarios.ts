import { Component, inject, input, signal } from '@angular/core';
import { Router } from '@angular/router';

import { ExecucoesService } from '../../core/api/execucoes.service';
import { dataCompleta } from '../../core/format/datas';
import { mensagemDeErro } from '../../core/http/api-error';

/**
 * Prazo dos comentários de uma execução (ADR-015).
 *
 * As políticas dos YouTube API Services não deixam guardar o texto dos comentários por
 * mais de 30 dias. Antes do prazo, a tela avisa até quando eles ficam; depois, explica
 * por que a lista sumiu, diz que os resultados continuam e oferece refazer a análise,
 * que é uma coleta nova. Usado no resultado, na lista de comentários e no relatório.
 */
@Component({
  selector: 'app-guarda-comentarios',
  template: `
    @if (apagadosEm(); as apagados) {
      <aside class="guarda guarda--apagados" role="status">
        <svg class="guarda__icone" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 7.5v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        </svg>
        <div class="guarda__texto">
          <p class="guarda__titulo">Os comentários desta análise foram apagados</p>
          <p>
            As políticas da API do YouTube não permitem guardar o texto dos comentários por mais de
            30 dias, e por isso ele saiu em {{ data(apagados) }}. Os percentuais, os temas e os
            indicadores continuam valendo.
          </p>
          @if (idModelo() && !impressao()) {
            <p>Para ler os comentários de novo, refaça a análise: ela faz uma coleta nova.</p>
            <div class="guarda__acoes">
              <button
                type="button"
                class="botao botao--secundario botao--pequeno"
                [disabled]="enviando()"
                (click)="refazer()"
              >
                {{ enviando() ? 'Enviando…' : 'Refazer a análise' }}
              </button>
              @if (falha(); as mensagem) {
                <span class="guarda__falha" role="alert">{{ mensagem }}</span>
              }
            </div>
          }
        </div>
      </aside>
    } @else if (disponiveisAte(); as ate) {
      <p class="guarda guarda--prazo">
        Os comentários desta análise ficam disponíveis até {{ data(ate) }}. Depois disso, as
        políticas da API do YouTube exigem apagar o texto; os resultados continuam.
      </p>
    }
  `,
  styles: `
    .guarda {
      display: flex;
      gap: var(--space-3);
      margin: 0 0 var(--space-4);
      padding: var(--space-3) var(--space-4);
      border-radius: var(--radius-card);
      background: var(--surface-muted);
      color: var(--ink-muted);
      font-size: 14px;
      line-height: 1.5;
    }
    .guarda--apagados {
      border: 1px solid var(--border);
      color: var(--ink);
    }
    .guarda__icone {
      width: 18px;
      height: 18px;
      flex: none;
      margin-top: 2px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.5;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .guarda__texto p {
      margin: 0 0 var(--space-2);
    }
    .guarda__texto p:last-child {
      margin-bottom: 0;
    }
    .guarda__titulo {
      font-weight: 600;
    }
    .guarda__acoes {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-3);
    }
    .guarda__falha {
      color: var(--negativo);
    }
  `,
})
export class GuardaComentarios {
  private readonly execucoes = inject(ExecucoesService);
  private readonly router = inject(Router);

  readonly disponiveisAte = input<string | null | undefined>(null);
  readonly apagadosEm = input<string | null | undefined>(null);
  /** Com o modelo, aparece o botão "Refazer a análise". */
  readonly idModelo = input<number | null>(null);
  /** No relatório impresso não há botão. */
  readonly impressao = input(false);

  protected readonly enviando = signal(false);
  protected readonly falha = signal<string | null>(null);

  protected data(iso: string): string {
    return dataCompleta(iso);
  }

  protected refazer(): void {
    const idModelo = this.idModelo();
    if (!idModelo) {
      return;
    }
    this.enviando.set(true);
    this.falha.set(null);
    this.execucoes.disparar(idModelo).subscribe({
      next: () => {
        this.enviando.set(false);
        void this.router.navigate(['/execucoes']);
      },
      error: (erro: unknown) => {
        this.enviando.set(false);
        this.falha.set(mensagemDeErro(erro, 'Não foi possível refazer a análise agora.'));
      },
    });
  }
}
