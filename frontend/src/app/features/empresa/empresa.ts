import { isPlatformBrowser } from '@angular/common';
import { Component, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { Convite, ConviteCriado, Membro } from '../../core/api/empresa.models';
import { EmpresaService } from '../../core/api/empresa.service';
import { PapelEmpresa } from '../../core/auth/auth.models';
import { AuthService } from '../../core/auth/auth.service';
import { dataLegivel } from '../../core/format/datas';
import { mensagemDeErro } from '../../core/http/api-error';

/**
 * Minha empresa (ADR-011): membros e convites.
 *
 * Todo membro vê a lista de membros. Só o DONO vê e usa as ações — gerar e
 * revogar convite, remover membro, tornar dono e tirar de dono (ADR-013).
 * Esconder os botões é conforto; quem barra de verdade é o backend, que
 * responde 403 para membro.
 */
@Component({
  selector: 'app-empresa',
  imports: [ReactiveFormsModule],
  templateUrl: './empresa.html',
  styleUrls: ['../painel/painel.css', '../conta/conta.css', './empresa.css'],
})
export class Empresa {
  private readonly api = inject(EmpresaService);
  private readonly auth = inject(AuthService);
  private readonly fb = inject(FormBuilder);
  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly usuario = this.auth.usuario;
  protected readonly ehDono = computed(() => this.usuario()?.papel_empresa === 'dono');

  protected readonly membros = signal<Membro[]>([]);
  protected readonly convites = signal<Convite[]>([]);
  protected readonly carregando = signal(true);
  protected readonly falha = signal<string | null>(null);

  /** O convite recém-criado: o link só existe aqui, e some ao sair da tela. */
  protected readonly criado = signal<ConviteCriado | null>(null);
  protected readonly copiado = signal(false);
  protected readonly convidando = signal(false);
  protected readonly erroConvite = signal<string | null>(null);

  /** Membro aguardando o segundo clique de "Remover". */
  protected readonly confirmando = signal<number | null>(null);
  /** Membro aguardando o segundo clique de "Tornar dono" / "Tirar de dono". */
  protected readonly confirmandoPapel = signal<number | null>(null);
  protected readonly erroAcao = signal<string | null>(null);

  protected readonly dataLegivel = dataLegivel;

  protected readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email, Validators.maxLength(255)]],
    papel_empresa: ['membro' as PapelEmpresa],
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

    this.api.membros().subscribe({
      next: (membros) => {
        this.membros.set(membros);
        this.carregando.set(false);
      },
      error: (erro: unknown) => {
        this.carregando.set(false);
        this.falha.set(mensagemDeErro(erro, 'Não foi possível carregar os membros.'));
      },
    });

    if (this.ehDono()) {
      this.carregarConvites();
    }
  }

  private carregarConvites(): void {
    this.api.convites().subscribe({
      next: (convites) => this.convites.set(convites),
      error: (erro: unknown) =>
        this.erroAcao.set(mensagemDeErro(erro, 'Não foi possível carregar os convites.')),
    });
  }

  protected convidar(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { email, papel_empresa } = this.form.getRawValue();
    this.convidando.set(true);
    this.erroConvite.set(null);
    this.criado.set(null);
    this.copiado.set(false);

    this.api.convidar({ email: email.trim(), papel_empresa }).subscribe({
      next: (convite) => {
        this.convidando.set(false);
        this.criado.set(convite);
        this.form.reset({ email: '', papel_empresa: 'membro' });
        this.carregarConvites();
      },
      error: (erro: unknown) => {
        this.convidando.set(false);
        this.erroConvite.set(mensagemDeErro(erro, 'Não foi possível gerar o convite.'));
      },
    });
  }

  protected async copiar(link: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(link);
      this.copiado.set(true);
    } catch {
      // Sem permissão de área de transferência: o link continua visível para copiar à mão.
      this.copiado.set(false);
    }
  }

  protected revogar(convite: Convite): void {
    this.erroAcao.set(null);
    this.api.revogarConvite(convite.id_convite).subscribe({
      next: () =>
        this.convites.update((lista) => lista.filter((c) => c.id_convite !== convite.id_convite)),
      error: (erro: unknown) =>
        this.erroAcao.set(mensagemDeErro(erro, 'Não foi possível revogar o convite.')),
    });
  }

  protected remover(membro: Membro): void {
    if (this.confirmando() !== membro.id_usuario) {
      this.confirmando.set(membro.id_usuario);
      return;
    }

    this.erroAcao.set(null);
    this.api.removerMembro(membro.id_usuario).subscribe({
      next: () => {
        this.confirmando.set(null);
        this.membros.update((lista) => lista.filter((m) => m.id_usuario !== membro.id_usuario));
      },
      error: (erro: unknown) => {
        this.confirmando.set(null);
        this.erroAcao.set(mensagemDeErro(erro, 'Não foi possível remover o membro.'));
      },
    });
  }

  /**
   * Promove ou rebaixa com dois cliques. O backend recusa (409) deixar a empresa
   * sem dono e passar do teto de donos; a mensagem dele vai para a tela.
   * Rebaixar a si mesmo é permitido se sobrar outro dono — e aí a sessão
   * recarrega o próprio usuário, para a tela perder as ações de dono na hora.
   */
  protected alterarPapel(membro: Membro): void {
    if (this.confirmandoPapel() !== membro.id_usuario) {
      this.confirmandoPapel.set(membro.id_usuario);
      return;
    }

    const novo: PapelEmpresa = membro.papel_empresa === 'dono' ? 'membro' : 'dono';
    this.erroAcao.set(null);
    this.api.alterarPapel(membro.id_usuario, novo).subscribe({
      next: (atualizado) => {
        this.confirmandoPapel.set(null);
        this.membros.update((lista) =>
          lista.map((m) => (m.id_usuario === atualizado.id_usuario ? atualizado : m)),
        );
        if (atualizado.id_usuario === this.usuario()?.id_usuario) {
          this.auth.loadCurrentUser().subscribe({ error: () => undefined });
        }
      },
      error: (erro: unknown) => {
        this.confirmandoPapel.set(null);
        this.erroAcao.set(mensagemDeErro(erro, 'Não foi possível alterar o papel.'));
      },
    });
  }

  protected rotuloPapel(membro: Membro): string {
    const confirmar = this.confirmandoPapel() === membro.id_usuario;
    if (membro.papel_empresa === 'dono') {
      return confirmar ? 'Confirmar: tirar de dono' : 'Tirar de dono';
    }
    return confirmar ? 'Confirmar: tornar dono' : 'Tornar dono';
  }

  protected podeRemover(membro: Membro): boolean {
    return this.ehDono() && membro.id_usuario !== this.usuario()?.id_usuario;
  }

  protected invalido(): boolean {
    const controle = this.form.controls.email;
    return controle.invalid && controle.touched;
  }
}
