import { Component, computed, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { AceiteTermos } from '../aceite-termos/aceite-termos';

interface NavItem {
  rotulo: string;
  rota: string;
  /** `d` de um <path> 24x24 — os ícones ficam inline para não puxar biblioteca. */
  icone: string;
}

/** O que a nav mostra sob o nome: o papel NA EMPRESA; admin global vem antes. */
const PAPEIS_EMPRESA: Record<string, string> = {
  dono: 'Dono',
  membro: 'Membro',
};

/**
 * Moldura das telas autenticadas: nav lateral fixa + área de conteúdo.
 *
 * É um componente de layout usado como rota-pai — as telas internas entram
 * no `<router-outlet>` daqui, então a nav não remonta a cada navegação.
 */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, AceiteTermos],
  templateUrl: './shell.html',
  styleUrl: './shell.css',
})
export class Shell {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly usuario = this.auth.usuario;

  private readonly itensBase: NavItem[] = [
    {
      rotulo: 'Início',
      rota: '/inicio',
      icone: 'M3 10.5 12 3l9 7.5M5.5 9.5V20h13V9.5',
    },
    {
      rotulo: 'Modelos de análise',
      rota: '/modelos',
      icone: 'M3.5 4.5h17v15h-17zM3.5 9.5h17M9 9.5V19.5',
    },
    {
      rotulo: 'Execuções',
      rota: '/execucoes',
      icone: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7.5V12l3 2',
    },
    {
      rotulo: 'Resultados',
      rota: '/resultados',
      icone: 'M4 20V12M9.33 20V6M14.67 20v-9M20 20V9',
    },
    {
      rotulo: 'Minha empresa',
      rota: '/empresa',
      icone: 'M4 20.5V5.5h9v15M13 9.5h7v11M7 9h3M7 13h3M7 17h3M16 13h1.5M16 17h1.5M2.5 20.5h19',
    },
  ];

  /** Item da administração: só aparece para o papel global `admin` (ADR-015). */
  private readonly itemAdmin: NavItem = {
    rotulo: 'Cota do YouTube',
    rota: '/admin/cota',
    icone: 'M4 20h16M6 20V10M10 20V4M14 20v-7M18 20v-11',
  };

  protected readonly itens = computed(() =>
    this.usuario()?.papel === 'admin' ? [...this.itensBase, this.itemAdmin] : this.itensBase,
  );

  /** ADR-012: abre o modal bloqueante e torna o resto da tela inerte. */
  protected readonly termosPendentes = computed(() => this.usuario()?.termos_pendentes === true);

  protected readonly empresa = computed(() => this.usuario()?.empresa?.nome ?? '');

  protected readonly iniciais = computed(() => {
    const nome = this.usuario()?.nome?.trim();
    if (!nome) {
      return '—';
    }
    const partes = nome.split(/\s+/);
    const primeira = partes[0]?.[0] ?? '';
    const ultima = partes.length > 1 ? (partes[partes.length - 1][0] ?? '') : '';
    return (primeira + ultima).toUpperCase();
  });

  protected readonly papel = computed(() => {
    const usuario = this.usuario();
    if (!usuario) {
      return '';
    }
    const naEmpresa = PAPEIS_EMPRESA[usuario.papel_empresa] ?? usuario.papel_empresa;
    return usuario.papel === 'admin' ? `Administrador · ${naEmpresa}` : naEmpresa;
  });

  protected sair(): void {
    this.auth.logout().subscribe({
      // A navegação acontece nos dois casos: `logout()` já zerou o estado local.
      next: () => void this.router.navigate(['/login']),
      error: () => void this.router.navigate(['/login']),
    });
  }
}
