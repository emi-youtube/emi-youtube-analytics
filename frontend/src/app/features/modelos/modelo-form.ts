import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Observable } from 'rxjs';

import { ExecucoesService } from '../../core/api/execucoes.service';
import { FiltrosModelo, ModeloAnalise } from '../../core/api/modelos.models';
import { ModelosService } from '../../core/api/modelos.service';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';
import { escreverVideos, lerVideos } from './videos';

/** Teto por execução do worker (`worker_max_comentarios_por_execucao`). */
const LIMITE_MAXIMO = 5000;

/** UC02 — cria (`POST`) e edita (`PATCH`) um modelo de análise. */
@Component({
  selector: 'app-modelo-form',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './modelo-form.html',
  styleUrls: ['../painel/painel.css', './modelo-form.css'],
})
export class ModeloForm {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ModelosService);
  private readonly execucoes = inject(ExecucoesService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  /** `null` em /modelos/novo. */
  private readonly idModelo: number | null = this.lerIdDaRota();

  /**
   * Filtros como vieram do servidor.
   *
   * O JSONB aceita chaves extras e o formulário só conhece três delas; sem
   * guardar o original, salvar apagaria silenciosamente o que outra parte do
   * sistema tiver gravado ali (`canais`, por exemplo).
   */
  private filtrosOriginais: FiltrosModelo = {};

  protected readonly limiteMaximo = LIMITE_MAXIMO;
  protected readonly edicao = this.idModelo !== null;
  protected readonly carregando = signal(this.idModelo !== null);
  protected readonly salvando = signal<'nenhum' | 'salvar' | 'executar'>('nenhum');
  protected readonly falha = signal<string | null>(null);
  /** Execução recusada por 409: o modelo foi salvo, a execução não nasceu. */
  protected readonly conflitoDeExecucao = signal(false);

  protected readonly form = this.fb.nonNullable.group({
    nome: ['', [Validators.required, Validators.maxLength(255)]],
    // O escopo do modelo vem daqui: `_validar_escopo` no servidor recusa o
    // modelo sem nenhum vídeo (UC02).
    videos: ['', [Validators.required]],
    termo_pesquisa: ['', [Validators.maxLength(255)]],
    publicado_apos: [''],
    limite_comentarios: [null as number | null, [Validators.min(1), Validators.max(LIMITE_MAXIMO)]],
  });

  /** Linhas do textarea que não são um ID nem um endereço de vídeo. */
  protected readonly linhasInvalidas = signal<string[]>([]);

  protected readonly ocupado = computed(() => this.salvando() !== 'nenhum');

  constructor() {
    if (this.idModelo !== null && this.isBrowser) {
      this.carregarModelo(this.idModelo);
    } else if (this.idModelo !== null) {
      // SSR: sem token não há o que buscar; o navegador carrega na hidratação.
      this.carregando.set(false);
    }
  }

  private lerIdDaRota(): number | null {
    const bruto = this.route.snapshot.paramMap.get('id');
    if (bruto === null) {
      return null;
    }
    const id = Number(bruto);
    return Number.isInteger(id) && id > 0 ? id : null;
  }

  private carregarModelo(idModelo: number): void {
    this.api.detalhar(idModelo).subscribe({
      next: (modelo) => {
        this.preencher(modelo);
        this.carregando.set(false);
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(
          statusDoErro(erro) === 404
            ? 'Este modelo não existe mais ou não é seu.'
            : mensagemDeErro(erro, 'Não foi possível carregar este modelo.'),
        );
      },
    });
  }

  private preencher(modelo: ModeloAnalise): void {
    this.filtrosOriginais = modelo.filtros ?? {};
    const { videos, publicado_apos, limite_comentarios } = this.filtrosOriginais;

    this.form.setValue({
      nome: modelo.nome,
      videos: escreverVideos(videos),
      termo_pesquisa: modelo.termo_pesquisa,
      publicado_apos: publicado_apos ?? '',
      limite_comentarios: limite_comentarios ?? null,
    });
  }

  /** Monta o `filtros` preservando as chaves que o formulário não conhece. */
  private montarFiltros(ids: string[]): FiltrosModelo {
    const { publicado_apos, limite_comentarios } = this.form.getRawValue();
    const filtros: FiltrosModelo = { ...this.filtrosOriginais, videos: ids };

    if (publicado_apos) {
      filtros.publicado_apos = publicado_apos;
    } else {
      delete filtros.publicado_apos;
    }

    if (limite_comentarios) {
      filtros.limite_comentarios = Number(limite_comentarios);
    } else {
      delete filtros.limite_comentarios;
    }

    return filtros;
  }

  protected salvar(executarDepois: boolean): void {
    const { ids, invalidas } = lerVideos(this.form.controls.videos.value);
    this.linhasInvalidas.set(invalidas);

    if (this.form.invalid || invalidas.length > 0 || ids.length === 0) {
      this.form.markAllAsTouched();
      if (ids.length === 0) {
        this.form.controls.videos.setErrors({ required: true });
      }
      return;
    }

    const { nome, termo_pesquisa } = this.form.getRawValue();
    const corpo = {
      nome: nome.trim(),
      termo_pesquisa: termo_pesquisa.trim(),
      filtros: this.montarFiltros(ids),
    };

    this.salvando.set(executarDepois ? 'executar' : 'salvar');
    this.falha.set(null);
    this.conflitoDeExecucao.set(false);

    const requisicao: Observable<ModeloAnalise> =
      this.idModelo === null ? this.api.criar(corpo) : this.api.atualizar(this.idModelo, corpo);

    requisicao.subscribe({
      next: (modelo) => {
        if (executarDepois) {
          this.dispararExecucao(modelo);
        } else {
          void this.router.navigateByUrl('/modelos');
        }
      },
      error: (erro: unknown) => {
        this.salvando.set('nenhum');
        this.falha.set(mensagemDeErro(erro, 'Não foi possível salvar este modelo.'));
      },
    });
  }

  /**
   * Segundo passo de "Salvar e executar agora".
   *
   * Erro aqui não desfaz o salvamento: o modelo existe e a tela precisa dizer
   * isso, senão o usuário tenta de novo e cria um modelo duplicado.
   */
  private dispararExecucao(modelo: ModeloAnalise): void {
    this.execucoes.disparar(modelo.id_modelo).subscribe({
      next: () => {
        void this.router.navigateByUrl('/execucoes');
      },
      error: (erro: unknown) => {
        this.salvando.set('nenhum');

        if (statusDoErro(erro) === 409) {
          // Só acontece na edição de um modelo que já está rodando.
          this.conflitoDeExecucao.set(true);
          return;
        }

        this.falha.set(
          mensagemDeErro(
            erro,
            'O modelo foi salvo, mas não foi possível iniciar a execução agora.',
          ),
        );
      },
    });
  }

  protected invalido(campo: 'nome' | 'videos' | 'limite_comentarios'): boolean {
    const controle = this.form.controls[campo];
    return controle.invalid && controle.touched;
  }
}
