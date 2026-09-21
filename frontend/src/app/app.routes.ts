import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth/auth.guard';

/**
 * Duas árvores: as telas de acesso (login e cadastro), públicas, e tudo o mais
 * pendurado no `Shell` sob o `authGuard` — assim uma tela nova nasce protegida
 * por estar no lugar certo, sem ninguém lembrar de repetir o guard.
 */
export const routes: Routes = [
  {
    path: 'login',
    title: 'Entrar · Emi YouTube Analytics',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/login/login').then((m) => m.Login),
  },
  {
    path: 'cadastro',
    title: 'Criar acesso · Emi YouTube Analytics',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/cadastro/cadastro').then((m) => m.Cadastro),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./layout/shell/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'inicio' },
      {
        path: 'inicio',
        title: 'Início · Emi YouTube Analytics',
        loadComponent: () => import('./features/inicio/inicio').then((m) => m.Inicio),
      },
      {
        path: 'modelos',
        title: 'Modelos de análise · Emi YouTube Analytics',
        loadComponent: () => import('./features/modelos/modelos').then((m) => m.Modelos),
      },
      {
        path: 'modelos/novo',
        title: 'Novo modelo · Emi YouTube Analytics',
        loadComponent: () => import('./features/modelos/modelo-form').then((m) => m.ModeloForm),
      },
      {
        path: 'modelos/:id/editar',
        title: 'Editar modelo · Emi YouTube Analytics',
        loadComponent: () => import('./features/modelos/modelo-form').then((m) => m.ModeloForm),
      },
      {
        path: 'execucoes',
        title: 'Execuções · Emi YouTube Analytics',
        loadComponent: () => import('./features/execucoes/execucoes').then((m) => m.Execucoes),
      },
      {
        path: 'resultados',
        title: 'Resultados · Emi YouTube Analytics',
        loadComponent: () =>
          import('./features/resultados/resultados-lista').then((m) => m.ResultadosLista),
      },
      {
        path: 'resultados/:id',
        title: 'Resultados da execução · Emi YouTube Analytics',
        loadComponent: () => import('./features/resultados/resultado').then((m) => m.Resultado),
      },
      {
        path: 'resultados/:id/comentarios',
        title: 'Comentários · Emi YouTube Analytics',
        loadComponent: () =>
          import('./features/comentarios/comentarios').then((m) => m.Comentarios),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
