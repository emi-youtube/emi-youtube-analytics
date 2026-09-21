import { Component, computed, input } from '@angular/core';

import { DistribuicaoSentimento, percentuais } from '../../core/api/dominio.models';

/**
 * Barra segmentada positivo / neutro / negativo.
 *
 * Aparece no destaque do Início, no resumo geral, em cada vídeo e em cada tema
 * do Dashboard — quatro tamanhos da mesma figura. Um componente só garante que
 * a ordem das cores e o arredondamento dos percentuais sejam sempre iguais.
 */
@Component({
  selector: 'app-barra-sentimento',
  template: `
    <div
      class="barra"
      [class.barra--rotulada]="rotulos()"
      role="img"
      [attr.aria-label]="descricao()"
    >
      @if (partes().positivo > 0) {
        <span class="faixa faixa--positivo" [style.width.%]="partes().positivo">
          @if (rotulos()) {
            <span class="faixa__texto">{{ partes().positivo }}%</span>
          }
        </span>
      }
      @if (partes().neutro > 0) {
        <span class="faixa faixa--neutro" [style.width.%]="partes().neutro">
          @if (rotulos()) {
            <span class="faixa__texto">{{ partes().neutro }}%</span>
          }
        </span>
      }
      @if (partes().negativo > 0) {
        <span class="faixa faixa--negativo" [style.width.%]="partes().negativo">
          @if (rotulos()) {
            <span class="faixa__texto">{{ partes().negativo }}%</span>
          }
        </span>
      }
    </div>
  `,
  styles: `
    .barra {
      display: flex;
      width: 100%;
      height: 10px;
      overflow: hidden;
      border-radius: var(--radius-pill);
      background: var(--neutro-soft);
    }

    .barra--rotulada {
      height: 44px;
      border-radius: var(--radius-control);
    }

    .faixa {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      min-width: 0;
      padding: 0;
    }

    .barra--rotulada .faixa {
      padding: 0 var(--space-3);
    }

    .faixa__texto {
      font-size: 14px;
      font-weight: 600;
      color: var(--surface);
      white-space: nowrap;
    }

    .faixa--positivo {
      background: var(--positivo);
    }

    .faixa--neutro {
      background: var(--neutro);
    }

    .faixa--negativo {
      background: var(--negativo);
    }
  `,
})
export class BarraSentimento {
  readonly distribuicao = input.required<DistribuicaoSentimento>();
  /** Escreve o percentual dentro de cada faixa (resumo grande do Dashboard). */
  readonly rotulos = input(false);

  protected readonly partes = computed(() => percentuais(this.distribuicao()));

  protected readonly descricao = computed(() => {
    const p = this.partes();
    return `${p.positivo}% positivo, ${p.neutro}% neutro, ${p.negativo}% negativo`;
  });
}
