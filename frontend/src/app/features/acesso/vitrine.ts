import { Component } from '@angular/core';

/**
 * Painel escuro à esquerda das telas de acesso (design/Main.png).
 *
 * É o mesmo bloco no login e no cadastro. Fica num componente próprio para
 * que um ajuste de discurso ou de marca valha para as duas telas de uma vez —
 * duas cópias do mesmo texto divergiriam na primeira revisão.
 */
@Component({
  selector: 'app-vitrine',
  template: `
    <div class="vitrine__marca">
      <svg class="vitrine__icone" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 15v5M9.33 10v10M14.67 13v7M20 4v16" />
      </svg>
      <span>Emi YouTube Analytics</span>
    </div>

    <div class="vitrine__discurso">
      <h1 class="vitrine__titulo">O que o público realmente achou da sua campanha.</h1>
      <p class="vitrine__texto">
        Colete os comentários dos seus vídeos publicitários, veja a divisão entre positivo, negativo
        e neutro, e descubra os temas que mais se repetem.
      </p>
    </div>

    <div class="vitrine__rodape">
      <p class="vitrine__escala">
        <span class="numeral vitrine__numero">500</span> a 5.000 comentários por execução
      </p>
      <p class="vitrine__lgpd">
        A identidade de quem comenta nunca é armazenada — apenas um código irreversível, em
        conformidade com a LGPD.
      </p>
    </div>
  `,
  styles: `
    /* O host é a própria coluna escura do grid de .acesso. */
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--space-6);
      background: var(--ink);
      color: var(--ink-on-dark);
      padding: var(--space-7) clamp(var(--space-5), 5vw, 64px);
    }

    .vitrine__marca {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 19px;
    }

    .vitrine__icone {
      width: 22px;
      height: 22px;
      flex: none;
      fill: none;
      stroke: var(--accent);
      stroke-width: 2.5;
      stroke-linecap: round;
    }

    .vitrine__discurso {
      margin-top: auto;
    }

    .vitrine__titulo {
      color: var(--ink-on-dark);
      font-size: clamp(32px, 4vw, 46px);
      letter-spacing: -0.01em;
      max-width: 15ch;
    }

    .vitrine__texto {
      margin-top: var(--space-5);
      max-width: 44ch;
      color: var(--ink-on-dark-muted);
    }

    .vitrine__rodape {
      margin-top: auto;
      padding-top: var(--space-5);
      border-top: 1px solid rgb(255 255 255 / 0.12);
    }

    .vitrine__escala {
      color: var(--ink-on-dark);
    }

    .vitrine__numero {
      color: var(--accent);
      font-size: 28px;
      margin-right: var(--space-2);
    }

    .vitrine__lgpd {
      margin-top: var(--space-3);
      font-size: 13px;
      color: var(--ink-on-dark-muted);
    }

    @media (max-width: 860px) {
      :host {
        gap: var(--space-5);
        padding: var(--space-5) var(--space-4);
      }

      .vitrine__discurso,
      .vitrine__rodape {
        margin-top: 0;
      }
    }
  `,
})
export class Vitrine {}
