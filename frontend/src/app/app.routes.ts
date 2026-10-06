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
    // Link do convite (`/entrar?convite=...`, ADR-011): a mesma tela do cadastro,
    // que lê o token e abre no modo "Tenho um convite".
    path: 'entrar',
    title: 'Entrar por convite · Emi YouTube Analytics',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/cadastro/cadastro').then((m) => m.Cadastro),
  },
  {
    path: 'esqueci-senha',
    title: 'Esqueci minha senha · Emi YouTube Analytics',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/senha/esqueci-senha').then((m) => m.EsqueciSenha),
  },
  {
    // Sem guard de propósito: o link do e-mail precisa abrir mesmo com uma sessão
    // antiga na aba — redefinir encerra essa sessão de qualquer jeito.
    path: 'redefinir-senha',
    title: 'Redefinir senha · Emi YouTube Analytics',
    loadComponent: () => import('./features/senha/redefinir-senha').then((m) => m.RedefinirSenha),
  },
  {
    // Termos e Política (ADR-012): públicos e sem guard nenhum — quem vai se
    // cadastrar lê antes, e quem já tem conta lê pelo modal de aceite sem ser
    // mandado para o início. Uma página só; `/privacidade` rola até a seção 4.
    path: 'termos',
    title: 'Termos de Uso · Emi YouTube Analytics',
    loadComponent: () => import('./features/legal/termos').then((m) => m.Termos),
  },
  {
    path: 'privacidade',
    title: 'Política de Privacidade · Emi YouTube Analytics',
    data: { secao: 'privacidade' },
    loadComponent: () => import('./features/legal/termos').then((m) => m.Termos),
  },
  {
    // Relatório de impressão (UC06): fora do Shell para sair sem o menu lateral,
    // e por isso repete o `authGuard` — é a única tela interna que não o herda.
    // Vem antes da árvore do Shell para não depender da ordem de casamento dela.
    path: 'resultados/:id/relatorio',
    title: 'Relatório · Emi YouTube Analytics',
    canActivate: [authGuard],
    loadComponent: () => import('./features/relatorio/relatorio').then((m) => m.Relatorio),
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
      {
        path: 'empresa',
        title: 'Minha empresa · Emi YouTube Analytics',
        loadComponent: () => import('./features/empresa/empresa').then((m) => m.Empresa),
      },
      {
        path: 'conta',
        title: 'Minha conta · Emi YouTube Analytics',
        loadComponent: () => import('./features/conta/conta').then((m) => m.Conta),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
