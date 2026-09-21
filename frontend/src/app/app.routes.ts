import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth/auth.guard';

/**
 * Duas árvores: o login, público, e tudo o mais pendurado no `Shell` sob o
 * `authGuard` — assim uma tela nova nasce protegida por estar no lugar certo,
 * sem ninguém lembrar de repetir o guard.
 */
export const routes: Routes = [
  {
    path: 'login',
    title: 'Entrar · Emi YouTube Analytics',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/login/login').then((m) => m.Login),
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
        data: {
          titulo: 'Início',
          descricao: 'Resumo das suas campanhas e da última coleta concluída.',
        },
        loadComponent: () => import('./features/em-breve/em-breve').then((m) => m.EmBreve),
      },
      {
        path: 'modelos',
        title: 'Modelos de análise · Emi YouTube Analytics',
        data: {
          titulo: 'Modelos de análise',
          descricao: 'Cadastre os vídeos e filtros de cada campanha que quer acompanhar.',
        },
        loadComponent: () => import('./features/em-breve/em-breve').then((m) => m.EmBreve),
      },
      {
        path: 'execucoes',
        title: 'Execuções · Emi YouTube Analytics',
        data: {
          titulo: 'Execuções',
          descricao: 'Acompanhe a coleta, a classificação e os temas de cada execução.',
        },
        loadComponent: () => import('./features/em-breve/em-breve').then((m) => m.EmBreve),
      },
      {
        path: 'resultados',
        title: 'Resultados · Emi YouTube Analytics',
        data: {
          titulo: 'Resultados',
          descricao: 'Sentimento, temas recorrentes e comentários de uma execução concluída.',
        },
        loadComponent: () => import('./features/em-breve/em-breve').then((m) => m.EmBreve),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
