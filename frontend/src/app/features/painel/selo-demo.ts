import { Component, inject } from '@angular/core';

import { DADOS_DE_DEMONSTRACAO } from '../../core/mock/mock.providers';

/**
 * Selo "Dados de demonstração".
 *
 * Toda tela que consome os serviços de análise inclui este componente. Ele lê
 * o mesmo token que escolhe mock ou API, então não existe estado em que a tela
 * mostre número inventado sem o aviso — e, quando a API real entrar, o selo
 * some sozinho das três telas.
 *
 * Discreto, mas legível em captura de tela: é justamente numa captura que o
 * número de demonstração pode ser confundido com resultado real.
 */
@Component({
  selector: 'app-selo-demo',
  template: `
    @if (demonstracao) {
      <p class="selo" role="note">
        <svg class="selo__icone" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5.5M12 7.75v.5" />
        </svg>
        <span
          ><strong>Dados de demonstração</strong> — números fictícios, ainda não vêm da análise
          real.</span
        >
      </p>
    }
  `,
  styles: `
    .selo {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      margin-bottom: var(--space-4);
      padding: 6px var(--space-3);
      border: 1px dashed var(--processando);
      border-radius: var(--radius-pill);
      background: var(--processando-soft);
      color: var(--processando);
      font-size: 13px;
      line-height: 1.35;
    }

    .selo__icone {
      width: 15px;
      height: 15px;
      flex: none;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.8;
    }

    @media (max-width: 600px) {
      .selo {
        border-radius: var(--radius-control);
        align-items: flex-start;
      }

      .selo__icone {
        margin-top: 2px;
      }
    }
  `,
})
export class SeloDemo {
  protected readonly demonstracao = inject(DADOS_DE_DEMONSTRACAO);
}
