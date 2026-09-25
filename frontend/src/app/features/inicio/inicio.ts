import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { ResumoPainel } from '../../core/api/painel.models';
import { PainelService } from '../../core/api/painel.service';
import { percentuais } from '../../core/api/dominio.models';
import { dataHoraLegivel, dataLegivel } from '../../core/format/datas';
import { mensagemDeErro } from '../../core/http/api-error';
import { BarraSentimento } from '../painel/barra-sentimento';
import { SeloDemo } from '../painel/selo-demo';

/** Tela Início (design/Home.png). Consome o recurso `painel`. */
@Component({
  selector: 'app-inicio',
  imports: [RouterLink, BarraSentimento, SeloDemo],
  templateUrl: './inicio.html',
  styleUrls: ['../painel/painel.css', './inicio.css'],
})
export class Inicio {
  private readonly api = inject(PainelService);
  private readonly auth = inject(AuthService);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly resumo = signal<ResumoPainel | null>(null);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);

  protected readonly dataLegivel = dataLegivel;
  protected readonly dataHoraLegivel = dataHoraLegivel;

  /**
   * "Bom dia, Marina" — montado aqui, e não no template.
   *
   * No template, a vírgula condicional exigiria interpolação colada no `@if`,
   * que o Prettier quebra em linhas e o HTML transforma em " , Marina".
   */
  protected readonly saudacao = computed(() => {
    const hora = new Date().getHours();
    const periodo = hora < 12 ? 'Bom dia' : hora < 18 ? 'Boa tarde' : 'Boa noite';
    const nome = this.auth.usuario()?.nome?.trim().split(/\s+/)[0];
    return nome ? `${periodo}, ${nome}` : periodo;
  });

  /**
   * "lexico-sentilex 1.0.0, em uso desde 24 set." — e, quando a versão tiver
   * avaliação, " F1 macro de 0,79 na validação." no fim.
   *
   * O nome sai da versão registrada na análise, nunca fixo aqui: o léxico é o
   * que está em produção hoje e o BERTimbau entra sem esta tela mudar.
   */
  protected readonly descricaoDoModelo = computed(() => {
    const versao = this.resumo()?.versao_modelo;
    if (!versao) {
      return '';
    }

    const desde = versao.em_uso_desde ? `, em uso desde ${dataLegivel(versao.em_uso_desde)}` : '';
    const f1 = versao.metricas_avaliacao
      ? ` F1 macro de ${versao.metricas_avaliacao.f1_macro.toFixed(2).replace('.', ',')} na validação.`
      : '';
    return `${versao.nome_modelo} ${versao.versao}${desde}.${f1}`;
  });

  protected readonly percentuaisDestaque = computed(() => {
    const destaque = this.resumo()?.destaque;
    return destaque ? percentuais(destaque.distribuicao) : null;
  });

  /** Fração 0..1 da cota consumida hoje, para a largura da barra. */
  protected readonly cotaUsada = computed(() => {
    const cota = this.resumo()?.cota_youtube;
    if (!cota || cota.unidades_limite <= 0) {
      return 0;
    }
    return Math.min(1, cota.unidades_usadas / cota.unidades_limite);
  });

  constructor() {
    // O token só existe no navegador; no SSR a tela sai como esqueleto e
    // carrega na hidratação (mesmo caminho das outras telas internas).
    if (this.isBrowser) {
      this.carregar();
    } else {
      this.carregando.set(false);
    }
  }

  protected carregar(): void {
    this.carregando.set(true);
    this.falha.set(null);

    this.api.carregar().subscribe({
      next: (resumo) => {
        this.resumo.set(resumo);
        this.carregando.set(false);
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(mensagemDeErro(erro, 'Não foi possível carregar o resumo.'));
      },
    });
  }

  /** Frase abaixo da saudação: o que mudou desde a última visita. */
  protected readonly recado = computed(() => {
    const resumo = this.resumo();
    if (!resumo) {
      return '';
    }
    const emAndamento = resumo.modelos.filter(
      (m) => m.status_ultima_execucao === 'processando' || m.status_ultima_execucao === 'pendente',
    ).length;

    if (emAndamento > 0) {
      return emAndamento === 1
        ? 'Uma execução está rodando agora.'
        : `${emAndamento} execuções estão rodando agora.`;
    }
    return resumo.destaque
      ? 'Uma coleta terminou desde a sua última visita.'
      : 'Crie um modelo de análise para começar.';
  });
}
