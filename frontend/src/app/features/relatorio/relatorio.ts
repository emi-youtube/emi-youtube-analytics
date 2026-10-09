import { DOCUMENT, NgTemplateOutlet, isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { DistribuicaoSentimento, Sentimento, percentuais } from '../../core/api/dominio.models';
import { FatoInsight, ResultadoExecucao } from '../../core/api/resultados.models';
import { ResultadosService } from '../../core/api/resultados.service';
import { dataCompleta, dataHoraCompleta } from '../../core/format/datas';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';
import { BarraSentimento } from '../painel/barra-sentimento';
import { SeloDemo } from '../painel/selo-demo';

/**
 * Abaixo disto o worker de tópicos não gera tema (`minimo_execucao` em
 * `backend/app/insights/configuracao.py`, usado por `topicos/modelo.py`).
 * Aqui serve só para EXPLICAR a ausência de temas — quem decide é o backend.
 */
const MINIMO_COMENTARIOS_TEMAS = 100;

/**
 * Relatório exportável da execução (UC06 "Gerar relatório estratégico").
 *
 * Página de impressão, não arquivo gerado no servidor: o navegador já sabe
 * salvar em PDF, e assim o relatório lê o MESMO `GET /execucoes/{id}/resultado`
 * da tela Resultados — não existe um segundo cálculo que possa divergir do
 * painel. Fica fora do `Shell` para não carregar o menu lateral; o layout A4
 * mora no `@media print` de `relatorio.css` e o `@page` em `styles.css`.
 */
@Component({
  selector: 'app-relatorio',
  imports: [RouterLink, NgTemplateOutlet, BarraSentimento, SeloDemo],
  templateUrl: './relatorio.html',
  styleUrl: './relatorio.css',
})
export class Relatorio {
  private readonly api = inject(ResultadosService);
  private readonly route = inject(ActivatedRoute);
  private readonly document = inject(DOCUMENT);
  private readonly titulo = inject(Title);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly idExecucao = Number(this.route.snapshot.paramMap.get('id'));

  protected readonly resultado = signal<ResultadoExecucao | null>(null);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);
  /** Momento em que os dados chegaram — é o que o rodapé chama de "gerado em". */
  protected readonly geradoEm = signal<Date | null>(null);

  protected readonly dataHoraCompleta = dataHoraCompleta;
  protected readonly dataCompleta = dataCompleta;
  protected readonly minimoTemas = MINIMO_COMENTARIOS_TEMAS;

  protected readonly percentuaisGerais = computed(() => {
    const r = this.resultado();
    return r ? percentuais(r.distribuicao) : null;
  });

  constructor() {
    // Mesmo motivo da tela Resultados: a sessão só existe no navegador, então
    // o servidor renderiza o esqueleto e a carga acontece na hidratação.
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
        this.geradoEm.set(new Date());
        this.carregando.set(false);
        // O título vira o nome sugerido do PDF no "Salvar como PDF".
        this.titulo.setTitle(
          `Relatório — ${resultado.nome_modelo_analise} — execução ${resultado.id_execucao}`,
        );
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        // 404 também é a execução de outro usuário: o backend não distingue,
        // e a tela não deve distinguir — não confirma que o id existe.
        this.falha.set(
          statusDoErro(erro) === 404
            ? 'Esta execução não tem resultados disponíveis.'
            : mensagemDeErro(erro, 'Não foi possível carregar o relatório.'),
        );
      },
    });
  }

  /** `window.print()` não existe no servidor; o botão só age no navegador. */
  protected imprimir(): void {
    if (this.isBrowser) {
      this.document.defaultView?.print();
    }
  }

  /** Percentual inteiro de uma parte; 0 quando não há total. */
  protected percentual(parte: number, total: number): number {
    return total > 0 ? Math.round((parte / total) * 100) : 0;
  }

  /** Proporção de negativos de um tema ou vídeo — a régua da PME. */
  protected negativos(d: DistribuicaoSentimento): number {
    return this.percentual(d.negativo, d.total);
  }

  /** `2026-09-01` -> `01/09/2026`, sem passar por `new Date` (fuso). */
  protected dataCivil(iso: string): string {
    const [ano, mes, dia] = iso.split('-');
    return `${dia}/${mes}/${ano}`;
  }

  protected numero(valor: number): string {
    return valor.toLocaleString('pt-BR');
  }

  protected rotuloSentimento(sentimento: Sentimento): string {
    return { positivo: 'Positivo', neutro: 'Neutro', negativo: 'Negativo' }[sentimento];
  }

  /** IDs do YouTube dos vídeos coletados — o recorte, como o usuário o cadastrou. */
  protected idsDosVideos(r: ResultadoExecucao): string {
    return r.videos.map((item) => item.video.youtube_video_id).join(', ');
  }

  /** "42 comentários (mínimo exigido: 30)" — o lastro do insight. */
  protected amostra(fato: FatoInsight): string {
    const { tamanho, minimo_exigido } = fato.amostra;
    return `${this.numero(tamanho)} comentários (mínimo exigido: ${this.numero(minimo_exigido)})`;
  }
}
