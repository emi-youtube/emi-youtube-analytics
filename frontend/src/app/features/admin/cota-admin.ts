import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, computed, inject, signal } from '@angular/core';

import { ConsumoDoDia, CotaAdmin as CotaAdminDados } from '../../core/api/admin.models';
import { AdminService } from '../../core/api/admin.service';
import { dataHoraLegivel } from '../../core/format/datas';
import { mensagemDeErro } from '../../core/http/api-error';

const NUMERO = new Intl.NumberFormat('pt-BR');
const DIA_CURTO = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  timeZone: 'UTC',
});

/** `AAAA-MM-DD` → `09/10`. O dia da cota é uma data, sem hora: lida em UTC. */
function diaCurto(dia: string): string {
  const data = new Date(`${dia}T00:00:00Z`);
  return Number.isNaN(data.getTime()) ? dia : DIA_CURTO.format(data);
}

/**
 * Administração · Cota do YouTube (ADR-015). Só o papel global `admin`.
 *
 * A cota é do projeto e a chave é uma só, então esta é a única tela que olha para
 * todas as empresas ao mesmo tempo. Mostra se a divisão está funcionando (quem
 * passou da fatia, quem está esperando) e guarda o histórico que o pedido de
 * ampliação de cota ao Google pede como "uso esperado".
 */
@Component({
  selector: 'app-cota-admin',
  templateUrl: './cota-admin.html',
  styleUrls: ['../painel/painel.css', '../execucoes/execucoes.css', './cota-admin.css'],
})
export class CotaAdmin {
  private readonly api = inject(AdminService);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly dados = signal<CotaAdminDados | null>(null);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);
  /** Dia sob o cursor no gráfico; sem cursor, a leitura mostra hoje. */
  protected readonly emFoco = signal<ConsumoDoDia | null>(null);

  protected readonly dataHoraLegivel = dataHoraLegivel;
  protected readonly diaCurto = diaCurto;
  protected readonly numero = (valor: number) => NUMERO.format(valor);

  /** Larguras da barra do dia, em % do limite. */
  protected readonly medidor = computed(() => {
    const d = this.dados();
    if (!d || d.limite <= 0) {
      return null;
    }
    const pct = (valor: number) => Math.min(100, (valor / d.limite) * 100);
    return {
      usado: pct(d.usado_hoje),
      folga: pct(d.teto_folga),
      teto: pct(d.limite - d.reserva),
    };
  });

  /** Altura de cada barra do histórico, relativa ao maior dia do período. */
  protected readonly barras = computed(() => {
    const d = this.dados();
    if (!d) {
      return [];
    }
    const escala = Math.max(d.pico_no_periodo, 1);
    return d.historico.map((ponto) => ({
      ...ponto,
      altura: ponto.unidades === 0 ? 0 : Math.max(2, (ponto.unidades / escala) * 100),
    }));
  });

  protected readonly leitura = computed(() => {
    const d = this.dados();
    const ponto = this.emFoco() ?? d?.historico.at(-1) ?? null;
    return ponto ? `${diaCurto(ponto.dia)} · ${NUMERO.format(ponto.unidades)} unidades` : '';
  });

  constructor() {
    // No SSR não há token; a tela carrega na hidratação (ver Modelos).
    if (this.isBrowser) {
      this.carregar();
    } else {
      this.carregando.set(false);
    }
  }

  protected carregar(): void {
    this.carregando.set(true);
    this.falha.set(null);
    this.api.cotaYoutube().subscribe({
      next: (dados) => {
        this.dados.set(dados);
        this.carregando.set(false);
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(mensagemDeErro(erro, 'Não foi possível carregar a cota.'));
      },
    });
  }

  protected percentualDaFatia(unidades: number): string {
    const fatia = this.dados()?.fatia_por_empresa ?? 0;
    return fatia > 0 ? `${Math.round((unidades / fatia) * 100)}%` : '—';
  }
}
