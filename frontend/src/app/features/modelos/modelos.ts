import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ModelosService } from '../../core/api/modelos.service';
import { ModeloAnalise, totalDeVideos } from '../../core/api/modelos.models';
import { dataLegivel } from '../../core/format/datas';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';

/** UC02 — lista dos modelos do usuário. Consome `GET /api/v1/modelos-analise`. */
@Component({
  selector: 'app-modelos',
  imports: [RouterLink],
  templateUrl: './modelos.html',
  styleUrls: ['../painel/painel.css', './modelos.css'],
})
export class Modelos {
  private readonly api = inject(ModelosService);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly modelos = signal<ModeloAnalise[]>([]);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);

  /** Modelo aguardando o segundo clique de "Excluir". */
  protected readonly confirmando = signal<number | null>(null);
  protected readonly removendo = signal<number | null>(null);
  /** Erro de exclusão por modelo: o 409 precisa aparecer no card certo. */
  protected readonly erroDeExclusao = signal<Record<number, string>>({});

  protected readonly totalDeVideos = totalDeVideos;
  protected readonly dataLegivel = dataLegivel;

  constructor() {
    // No SSR não há token (ele vive em memória no navegador), então a requisição
    // voltaria 401 e o HTML do servidor mostraria um erro falso. A tela carrega
    // na hidratação.
    if (this.isBrowser) {
      this.carregar();
    } else {
      this.carregando.set(false);
    }
  }

  protected carregar(): void {
    this.carregando.set(true);
    this.falha.set(null);

    this.api.listar().subscribe({
      next: (modelos) => {
        this.modelos.set(modelos);
        this.carregando.set(false);
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(mensagemDeErro(erro, 'Não foi possível carregar seus modelos.'));
      },
    });
  }

  protected pedirConfirmacao(idModelo: number): void {
    this.limparErro(idModelo);
    this.confirmando.set(idModelo);
  }

  protected cancelarExclusao(): void {
    this.confirmando.set(null);
  }

  protected excluir(modelo: ModeloAnalise): void {
    this.removendo.set(modelo.id_modelo);
    this.limparErro(modelo.id_modelo);

    this.api.remover(modelo.id_modelo).subscribe({
      next: () => {
        this.removendo.set(null);
        this.confirmando.set(null);
        this.modelos.update((lista) => lista.filter((m) => m.id_modelo !== modelo.id_modelo));
      },
      error: (erro: unknown) => {
        this.removendo.set(null);
        this.confirmando.set(null);
        this.erroDeExclusao.update((erros) => ({
          ...erros,
          [modelo.id_modelo]: this.mensagemDeExclusao(erro),
        }));
      },
    });
  }

  /**
   * O 409 do DELETE não é falha de rede nem de permissão: é a regra de que
   * apagar o modelo apagaria o histórico das execuções que dependem dele
   * (`delete` em `backend/app/services/modelo_analise.py`).
   */
  private mensagemDeExclusao(erro: unknown): string {
    if (statusDoErro(erro) === 409) {
      return 'Este modelo já foi executado e por isso não pode ser excluído — remover o modelo apagaria o histórico das execuções dele.';
    }
    return mensagemDeErro(erro, 'Não foi possível excluir este modelo.');
  }

  protected limparErro(idModelo: number): void {
    this.erroDeExclusao.update((erros) => {
      const { [idModelo]: _removido, ...resto } = erros;
      return resto;
    });
  }
}
