import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ResultadoDisponivel } from '../../core/api/resultados.models';
import { ResultadosService } from '../../core/api/resultados.service';
import { dataHoraLegivel } from '../../core/format/datas';
import { mensagemDeErro } from '../../core/http/api-error';
import { BarraSentimento } from '../painel/barra-sentimento';
import { SeloDemo } from '../painel/selo-demo';

/**
 * Escolha de qual execução ver (`/resultados`).
 *
 * Não está nos mockups, que começam já dentro de um resultado. Existe porque
 * "Resultados" é item fixo da nav lateral: sem esta tela, o link levaria a
 * lugar nenhum enquanto o usuário não viesse por um atalho do Início.
 */
@Component({
  selector: 'app-resultados-lista',
  imports: [RouterLink, BarraSentimento, SeloDemo],
  templateUrl: './resultados-lista.html',
  styleUrls: ['../painel/painel.css', './resultados-lista.css'],
})
export class ResultadosLista {
  private readonly api = inject(ResultadosService);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly disponiveis = signal<ResultadoDisponivel[]>([]);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);

  protected readonly dataHoraLegivel = dataHoraLegivel;

  constructor() {
    if (this.isBrowser) {
      this.carregar();
    } else {
      this.carregando.set(false);
    }
  }

  protected carregar(): void {
    this.carregando.set(true);
    this.falha.set(null);

    this.api.listarDisponiveis().subscribe({
      next: (lista) => {
        this.disponiveis.set(lista);
        this.carregando.set(false);
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(mensagemDeErro(erro, 'Não foi possível carregar os resultados.'));
      },
    });
  }

  protected numero(valor: number): string {
    return valor.toLocaleString('pt-BR');
  }
}
