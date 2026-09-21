import { RenderMode, ServerRoute } from '@angular/ssr';

/**
 * SSR de verdade (render por requisição), não pré-render.
 *
 * As telas internas dependem de sessão, que só existe no navegador — o
 * servidor não teria o que congelar num HTML estático. O `login` poderia ser
 * pré-renderizado, mas manter uma regra só evita que uma rota nova nasça
 * estática por engano.
 */
export const serverRoutes: ServerRoute[] = [
  {
    path: '**',
    renderMode: RenderMode.Server,
  },
];
