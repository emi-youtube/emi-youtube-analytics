import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { Sentimento, percentuais } from '../../core/api/dominio.models';
import { ResultadoExecucao, VideoComSentimento } from '../../core/api/resultados.models';
import { ResultadosService } from '../../core/api/resultados.service';
import { dataHoraLegivel } from '../../core/format/datas';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';
import { BarraSentimento } from '../painel/barra-sentimento';
import { SeloDemo } from '../painel/selo-demo';

/** Acima disto o vídeo é destacado como fora da curva (design/Dashboard.png). */
const FATOR_NEGATIVIDADE_ALTA = 2;

/** Tela Resultados de uma execução (design/Dashboard.png). */
@Component({
  selector: 'app-resultado',
  imports: [RouterLink, BarraSentimento, SeloDemo],
  templateUrl: './resultado.html',
  styleUrls: ['../painel/painel.css', './resultado.css'],
})
export class Resultado {
  private readonly api = inject(ResultadosService);
  private readonly route = inject(ActivatedRoute);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  private readonly idExecucao = Number(this.route.snapshot.paramMap.get('id'));

  protected readonly resultado = signal<ResultadoExecucao | null>(null);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);

  protected readonly dataHoraLegivel = dataHoraLegivel;

  protected readonly percentuaisGerais = computed(() => {
    const r = this.resultado();
    return r ? percentuais(r.distribuicao) : null;
  });

  /**
   * Percentual negativo médio da execução — a régua para apontar o vídeo fora
   * da curva. Fica aqui, e não no servidor, porque é só leitura da tela.
   */
  private readonly negatividadeMedia = computed(() => {
    const r = this.resultado();
    return r && r.distribuicao.total > 0 ? r.distribuicao.negativo / r.distribuicao.total : 0;
  });

  constructor() {
    if (this.isBrowser) {
      this.carregar();
    } else {
      this.carregando.set(false);
    }
  }

  protected carregar(): void {
    if (!Number.isInteger(this.idExecucao) || this.idExecucao <= 0) {
      this.carregando.set(false);
      this.falha.set('Execução inválida.');
      return;
    }

    this.carregando.set(true);
    this.falha.set(null);

    this.api.carregar(this.idExecucao).subscribe({
      next: (resultado) => {
        this.resultado.set(resultado);
        this.carregando.set(false);
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(
          statusDoErro(erro) === 404
            ? 'Esta execução não tem resultados disponíveis.'
            : mensagemDeErro(erro, 'Não foi possível carregar os resultados.'),
        );
      },
    });
  }

  /** Vídeo com negatividade muito acima da média da própria execução. */
  protected foraDaCurva(item: VideoComSentimento): boolean {
    const { negativo, total } = item.distribuicao;
    if (total === 0 || this.negatividadeMedia() === 0) {
      return false;
    }
    return negativo / total >= this.negatividadeMedia() * FATOR_NEGATIVIDADE_ALTA;
  }

  protected rotuloForaDaCurva(item: VideoComSentimento): string {
    const proporcao =
      item.distribuicao.negativo / item.distribuicao.total / this.negatividadeMedia();
    return `${proporcao.toFixed(1).replace('.0', '').replace('.', ',')}× a negatividade média`;
  }

  /** "512 mil", "1,4 mi" — número grande legível, como no design. */
  protected abreviar(valor: number): string {
    if (valor >= 1_000_000) {
      return `${(valor / 1_000_000).toFixed(1).replace('.', ',')} mi`;
    }
    if (valor >= 1_000) {
      return `${Math.round(valor / 1_000)} mil`;
    }
    return valor.toLocaleString('pt-BR');
  }

  protected numero(valor: number): string {
    return valor.toLocaleString('pt-BR');
  }

  protected rotuloSentimento(sentimento: Sentimento): string {
    return { positivo: 'Positivo', neutro: 'Neutro', negativo: 'Negativo' }[sentimento];
  }
}
