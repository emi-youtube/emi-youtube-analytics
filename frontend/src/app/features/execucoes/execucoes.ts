import { isPlatformBrowser } from '@angular/common';
import { Component, DestroyRef, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Observable, Subscription, catchError, forkJoin, map, of, switchMap, timer } from 'rxjs';

import {
  Execucao,
  ROTULOS_STATUS,
  StatusExecucao,
  estaAtiva,
} from '../../core/api/execucoes.models';
import { ExecucoesService } from '../../core/api/execucoes.service';
import { ModeloAnalise } from '../../core/api/modelos.models';
import { ModelosService } from '../../core/api/modelos.service';
import { dataHoraLegivel } from '../../core/format/datas';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';

/**
 * Intervalo do polling do UC04.
 *
 * 3s é curto o bastante para a mudança parecer imediata e longo o bastante
 * para não martelar a API: a coleta leva minutos, não milissegundos.
 */
const INTERVALO_POLLING_MS = 3000;

/** UC03/UC04 — dispara execuções e acompanha o andamento delas. */
@Component({
  selector: 'app-execucoes',
  imports: [FormsModule, RouterLink],
  templateUrl: './execucoes.html',
  styleUrls: ['../painel/painel.css', './execucoes.css'],
})
export class Execucoes {
  private readonly api = inject(ExecucoesService);
  private readonly modelosApi = inject(ModelosService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly execucoes = signal<Execucao[]>([]);
  protected readonly modelos = signal<ModeloAnalise[]>([]);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);

  protected readonly painelAberto = signal(false);
  protected modeloEscolhido: number | null = null;
  protected readonly disparando = signal(false);
  protected readonly erroDisparo = signal<string | null>(null);

  protected readonly rotulos = ROTULOS_STATUS;
  protected readonly dataHoraLegivel = dataHoraLegivel;

  /** Enquanto houver uma destas, o polling continua. */
  private readonly ativas = computed(() => this.execucoes().filter((e) => estaAtiva(e.status)));

  /** A execução só traz `id_modelo`; o nome vem da lista de modelos. */
  private readonly nomePorModelo = computed(() => {
    const mapa = new Map<number, string>();
    for (const modelo of this.modelos()) {
      mapa.set(modelo.id_modelo, modelo.nome);
    }
    return mapa;
  });

  /** Um modelo com execução ativa não aceita outra (regra do UC03). */
  protected readonly modelosOcupados = computed(
    () => new Set(this.ativas().map((e) => e.id_modelo)),
  );

  protected readonly resumo = computed(() => {
    const contagem = { pendente: 0, processando: 0, concluida: 0, erro: 0 };
    for (const execucao of this.execucoes()) {
      contagem[execucao.status] += 1;
    }
    return contagem;
  });

  private pollingSub: Subscription | null = null;

  constructor() {
    if (this.isBrowser) {
      this.carregar();
    } else {
      // SSR não tem token: a tela chega vazia e carrega na hidratação.
      this.carregando.set(false);
    }
  }

  protected nomeDoModelo(idModelo: number): string {
    return this.nomePorModelo().get(idModelo) ?? `Modelo #${idModelo}`;
  }

  protected classeDoBadge(status: StatusExecucao): string {
    return `badge badge--${status}`;
  }

  protected carregar(): void {
    this.carregando.set(true);
    this.falha.set(null);

    // Os dois juntos: sem os modelos a tabela mostraria só o id do modelo.
    forkJoin({
      execucoes: this.api.listar(),
      modelos: this.modelosApi.listar(),
    }).subscribe({
      next: ({ execucoes, modelos }) => {
        this.execucoes.set(execucoes);
        this.modelos.set(modelos);
        this.carregando.set(false);
        this.acompanharAtivas();
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(mensagemDeErro(erro, 'Não foi possível carregar as execuções.'));
      },
    });
  }

  // --- Disparo (UC03) ---

  protected alternarPainel(): void {
    this.erroDisparo.set(null);
    this.painelAberto.update((aberto) => !aberto);
  }

  protected disparar(): void {
    const idModelo = Number(this.modeloEscolhido);
    if (!idModelo) {
      return;
    }

    this.disparando.set(true);
    this.erroDisparo.set(null);

    this.api.disparar(idModelo).subscribe({
      next: (execucao) => {
        this.disparando.set(false);
        this.painelAberto.set(false);
        this.modeloEscolhido = null;
        // O 202 já devolve a execução em 'pendente': ela entra na lista agora,
        // sem esperar worker nem recarregar a página. É o "aceito" visível.
        this.execucoes.update((lista) => [execucao, ...lista]);
        this.acompanharAtivas();
      },
      error: (erro: unknown) => {
        this.disparando.set(false);

        if (statusDoErro(erro) === 409) {
          // O botão já fica desabilitado para modelo ocupado, mas entre o
          // desenho da tela e o clique outra aba pode ter disparado a execução.
          this.erroDisparo.set(
            'Este modelo já tem uma execução em andamento. A lista abaixo foi atualizada.',
          );
          this.recarregarExecucoes();
          return;
        }

        this.erroDisparo.set(mensagemDeErro(erro, 'Não foi possível iniciar a execução.'));
      },
    });
  }

  /** Releitura silenciosa da lista — usada depois de um 409. */
  private recarregarExecucoes(): void {
    this.api.listar().subscribe({
      next: (execucoes) => {
        this.execucoes.set(execucoes);
        this.acompanharAtivas();
      },
      error: () => undefined,
    });
  }

  // --- Acompanhamento (UC04) ---

  /**
   * Liga o polling enquanto houver execução pendente ou processando.
   *
   * Idempotente de propósito: é chamada depois da carga e depois de cada
   * disparo, e não pode abrir uma segunda assinatura em cima da primeira.
   */
  private acompanharAtivas(): void {
    if (!this.isBrowser || this.pollingSub || this.ativas().length === 0) {
      return;
    }

    this.pollingSub = timer(INTERVALO_POLLING_MS, INTERVALO_POLLING_MS)
      .pipe(
        switchMap(() => this.consultarAtivas()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((atualizadas) => {
        this.aplicar(atualizadas);

        // Fim do ciclo: todas terminaram em 'concluida' ou 'erro'. Continuar
        // consultando seria bater na API para sempre por um dado que não muda.
        if (this.ativas().length === 0) {
          this.pararPolling();
        }
      });
  }

  private consultarAtivas(): Observable<Execucao[]> {
    const ativas = this.ativas();
    if (ativas.length === 0) {
      return of([]);
    }

    return forkJoin(
      ativas.map((execucao) =>
        this.api.detalhar(execucao.id_execucao).pipe(
          // Uma falha de rede não pode derrubar o acompanhamento: esta volta
          // fica sem resposta e a próxima tenta de novo.
          catchError(() => of(null)),
        ),
      ),
    ).pipe(map((respostas) => respostas.filter((r): r is Execucao => r !== null)));
  }

  private aplicar(atualizadas: Execucao[]): void {
    if (atualizadas.length === 0) {
      return;
    }
    const porId = new Map(atualizadas.map((e) => [e.id_execucao, e]));
    this.execucoes.update((lista) => lista.map((e) => porId.get(e.id_execucao) ?? e));
  }

  private pararPolling(): void {
    this.pollingSub?.unsubscribe();
    this.pollingSub = null;
  }
}
