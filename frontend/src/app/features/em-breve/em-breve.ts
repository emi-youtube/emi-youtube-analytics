import { Component, input } from '@angular/core';

/**
 * Espaço reservado das telas internas.
 *
 * A fundação da Sprint 5 entrega nav, sessão e rotas; Início, Modelos de
 * análise, Execuções e Resultados entram nas etapas seguintes. Até lá, as
 * quatro rotas apontam para cá — assim a nav é navegável de verdade e nenhum
 * link leva a 404.
 *
 * Título e descrição vêm do `data` da rota via `withComponentInputBinding()`.
 */
@Component({
  selector: 'app-em-breve',
  template: `
    <header class="cabecalho">
      <h1>{{ titulo() }}</h1>
      <p class="muted">{{ descricao() }}</p>
    </header>

    <div class="card reservado">
      <p class="muted">Esta tela será construída na próxima etapa da Sprint 5.</p>
    </div>
  `,
  styles: `
    .cabecalho {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      margin-bottom: var(--space-5);
    }

    .reservado {
      padding: var(--space-6);
      text-align: center;
    }
  `,
})
export class EmBreve {
  readonly titulo = input.required<string>();
  readonly descricao = input('');
}
