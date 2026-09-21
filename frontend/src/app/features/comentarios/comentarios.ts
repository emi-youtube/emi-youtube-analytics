import { isPlatformBrowser } from '@angular/common';
import { Component, DestroyRef, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Params, Router, RouterLink } from '@angular/router';
import { Subject, debounceTime, distinctUntilChanged, forkJoin, of, switchMap } from 'rxjs';

import {
  FiltroComentarios,
  PaginaComentarios,
  TAMANHO_PAGINA_PADRAO,
} from '../../core/api/comentarios.models';
import { ComentariosService } from '../../core/api/comentarios.service';
import { Sentimento } from '../../core/api/dominio.models';
import { ResultadoExecucao } from '../../core/api/resultados.models';
import { ResultadosService } from '../../core/api/resultados.service';
import { dataLegivel } from '../../core/format/datas';
import { mensagemDeErro } from '../../core/http/api-error';
import { SeloDemo } from '../painel/selo-demo';

/** Abaixo disto a tela sugere conferência humana (design/Comentarios.png). */
const CONFIANCA_MINIMA = 0.6;

const SENTIMENTOS: readonly Sentimento[] = ['positivo', 'neutro', 'negativo'];

/** Tela Comentários de uma execução (design/Comentarios.png). */
@Component({
  selector: 'app-comentarios',
  imports: [FormsModule, RouterLink, SeloDemo],
  templateUrl: './comentarios.html',
  styleUrls: ['../painel/painel.css', './comentarios.css'],
})
export class Comentarios {
  private readonly api = inject(ComentariosService);
  private readonly resultadosApi = inject(ResultadosService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly idExecucao = Number(this.route.snapshot.paramMap.get('id'));

  /** Contexto da execução: título da tela e opções dos filtros. */
  protected readonly resultado = signal<ResultadoExecucao | null>(null);
  protected readonly pagina = signal<PaginaComentarios | null>(null);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);

  protected readonly sentimentos = SENTIMENTOS;
  protected readonly dataLegivel = dataLegivel;

  /** Ligado ao campo de busca; o filtro em si só muda depois do debounce. */
  protected texto = '';
  private readonly digitacao = new Subject<string>();

  /** Espelha a query string — é ela que manda no estado da tela. */
  protected readonly filtro = signal<FiltroComentarios>({
    pagina: 1,
    tamanho: TAMANHO_PAGINA_PADRAO,
  });

  protected readonly temaSelecionado = computed(() => {
    const id = this.filtro().id_tema;
    return this.resultado()?.temas.find((t) => t.tema.id_tema === id)?.tema ?? null;
  });

  protected readonly totalPaginas = computed(() => {
    const p = this.pagina();
    return p ? Math.max(1, Math.ceil(p.total / p.tamanho)) : 1;
  });

  protected readonly primeiroDaPagina = computed(() => {
    const p = this.pagina();
    return p && p.total > 0 ? (p.pagina - 1) * p.tamanho + 1 : 0;
  });

  protected readonly ultimoDaPagina = computed(() => {
    const p = this.pagina();
    return p ? Math.min(p.pagina * p.tamanho, p.total) : 0;
  });

  constructor() {
    if (!this.isBrowser) {
      // SSR: sem sessão não há o que buscar; o navegador carrega na hidratação.
      this.carregando.set(false);
      return;
    }

    this.carregarContexto();

    // A query string é a fonte da verdade: voltar no histórico ou colar o
    // link com ?tema= tem que reconstruir exatamente a mesma tela.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.filtro.set(lerFiltro(params.keys.map((k) => [k, params.get(k)])));
      this.texto = this.filtro().busca ?? '';
      this.buscar();
    });

    this.digitacao
      .pipe(debounceTime(350), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((busca) => this.aplicar({ busca: busca || null, pagina: null }));
  }

  private carregarContexto(): void {
    forkJoin({ resultado: this.resultadosApi.carregar(this.idExecucao) })
      .pipe(switchMap(({ resultado }) => of(resultado)))
      .subscribe({
        next: (resultado) => this.resultado.set(resultado),
        // Sem contexto a lista ainda funciona: os selects é que ficam vazios.
        error: () => undefined,
      });
  }

  private buscar(): void {
    this.carregando.set(true);
    this.falha.set(null);

    this.api.listar(this.idExecucao, this.filtro()).subscribe({
      next: (pagina) => {
        this.pagina.set(pagina);
        this.carregando.set(false);
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(mensagemDeErro(erro, 'Não foi possível carregar os comentários.'));
      },
    });
  }

  /**
   * Escreve o filtro na URL; a assinatura de `queryParamMap` é quem recarrega.
   *
   * `null` remove o parâmetro. Mudança de filtro sempre volta para a página 1 —
   * senão a pessoa filtra e cai numa página vazia.
   */
  private aplicar(mudancas: Params): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { pagina: null, ...mudancas },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  protected aoDigitar(valor: string): void {
    this.digitacao.next(valor.trim());
  }

  protected escolherTema(valor: string): void {
    this.aplicar({ tema: valor ? valor : null });
  }

  protected escolherVideo(valor: string): void {
    this.aplicar({ video: valor ? valor : null });
  }

  protected escolherSentimento(sentimento: Sentimento | null): void {
    this.aplicar({ sentimento });
  }

  protected irPara(pagina: number): void {
    this.aplicar({ pagina: pagina <= 1 ? null : pagina });
  }

  protected rotuloSentimento(sentimento: Sentimento): string {
    return { positivo: 'Positivo', neutro: 'Neutro', negativo: 'Negativo' }[sentimento];
  }

  /** O modelo ficou em cima do muro: vale conferência humana. */
  protected revisaoSugerida(confianca: number | null): boolean {
    return confianca !== null && confianca < CONFIANCA_MINIMA;
  }

  protected peso(valor: number): string {
    return valor.toFixed(2).replace('.', ',');
  }
}

/** Traduz a query string para o filtro, ignorando valor fora do esperado. */
function lerFiltro(entradas: [string, string | null][]): FiltroComentarios {
  const bruto = new Map(entradas);
  const inteiro = (chave: string): number | undefined => {
    const valor = Number(bruto.get(chave));
    return Number.isInteger(valor) && valor > 0 ? valor : undefined;
  };

  const sentimento = bruto.get('sentimento');
  const busca = bruto.get('busca')?.trim();

  return {
    busca: busca || undefined,
    id_tema: inteiro('tema'),
    id_video: inteiro('video'),
    sentimento: SENTIMENTOS.includes(sentimento as Sentimento)
      ? (sentimento as Sentimento)
      : undefined,
    pagina: inteiro('pagina') ?? 1,
    tamanho: TAMANHO_PAGINA_PADRAO,
  };
}
