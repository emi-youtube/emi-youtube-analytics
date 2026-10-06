import { DOCUMENT } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { ContaService } from '../../core/api/conta.service';
import { Membro } from '../../core/api/empresa.models';
import { EmpresaService } from '../../core/api/empresa.service';
import { AuthService } from '../../core/auth/auth.service';
import { SENHA_MINIMA, senhasConferem } from '../../core/auth/senha';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';

/**
 * O que excluir a conta faz, por papel (ADR-013) — espelha `conta.excluir_conta`:
 * - `membro`: sai a conta; os modelos passam a um dono;
 * - `dono_sozinho`: sai a empresa inteira;
 * - `dono_com_outro_dono`: sai a conta; os modelos passam ao outro dono;
 * - `dono_unico_com_membros`: recusado até promover alguém a dono.
 */
export type SituacaoDeSaida =
  'membro' | 'dono_sozinho' | 'dono_com_outro_dono' | 'dono_unico_com_membros';

/**
 * Minha conta: dados de quem está logado, troca de senha e os direitos do
 * titular (ADR-012) — baixar os dados e excluir a conta.
 * Consome `POST /api/v1/auth/trocar-senha`, `GET /api/v1/conta/meus-dados` e
 * `DELETE /api/v1/conta`.
 */
@Component({
  selector: 'app-conta',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './conta.html',
  styleUrls: ['../painel/painel.css', './conta.css'],
})
export class Conta {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly conta = inject(ContaService);
  private readonly router = inject(Router);
  private readonly documento = inject(DOCUMENT);
  private readonly empresa = inject(EmpresaService);

  protected readonly usuario = this.auth.usuario;
  protected readonly senhaMinima = SENHA_MINIMA;
  protected readonly enviando = signal(false);
  protected readonly sucesso = signal(false);
  protected readonly erro = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group(
    {
      senha_atual: ['', [Validators.required]],
      nova_senha: ['', [Validators.required, Validators.minLength(SENHA_MINIMA)]],
      confirmacao: ['', [Validators.required]],
    },
    { validators: senhasConferem('nova_senha') },
  );

  /** Membros da empresa: só buscados para o dono, que precisa saber quem fica. */
  private readonly membros = signal<Membro[] | null>(null);
  private membrosPedidos = false;

  /** `null` enquanto a lista de membros do dono não chega. */
  protected readonly situacao = computed<SituacaoDeSaida | null>(() => {
    const eu = this.usuario();
    if (!eu) {
      return null;
    }
    if (eu.papel_empresa !== 'dono') {
      return 'membro';
    }
    const membros = this.membros();
    if (membros === null) {
      return null;
    }
    const outros = membros.filter((m) => m.id_usuario !== eu.id_usuario);
    if (outros.length === 0) {
      return 'dono_sozinho';
    }
    return outros.some((m) => m.papel_empresa === 'dono')
      ? 'dono_com_outro_dono'
      : 'dono_unico_com_membros';
  });

  constructor() {
    // A sessão pode chegar depois do componente (hidratação): busca quando souber
    // que é dono, uma vez só.
    effect(() => {
      if (this.usuario()?.papel_empresa === 'dono' && !this.membrosPedidos) {
        this.membrosPedidos = true;
        this.empresa.membros().subscribe({
          next: (lista) => this.membros.set(lista),
          // Sem a lista, a tela fica no texto mais cauteloso; o backend decide.
          error: () => this.membros.set([]),
        });
      }
    });
  }

  protected readonly baixando = signal(false);
  protected readonly erroDownload = signal<string | null>(null);

  protected readonly excluindo = signal(false);
  protected readonly erroExclusao = signal<string | null>(null);
  protected readonly exclusao = this.fb.nonNullable.group({
    senha: ['', [Validators.required]],
  });

  /** Baixa `GET /conta/meus-dados` como arquivo JSON (LGPD, art. 18, II). */
  protected baixarDados(): void {
    this.baixando.set(true);
    this.erroDownload.set(null);
    this.conta.meusDados().subscribe({
      next: (dados) => {
        this.baixando.set(false);
        const blob = new Blob([JSON.stringify(dados, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = this.documento.createElement('a');
        link.href = url;
        link.download = 'meus-dados-emi-analytics.json';
        link.click();
        URL.revokeObjectURL(url);
      },
      error: (erro: unknown) => {
        this.baixando.set(false);
        this.erroDownload.set(mensagemDeErro(erro, 'Não foi possível baixar os dados.'));
      },
    });
  }

  protected excluirConta(): void {
    if (this.exclusao.invalid) {
      this.exclusao.markAllAsTouched();
      return;
    }
    this.excluindo.set(true);
    this.erroExclusao.set(null);
    this.conta.excluir(this.exclusao.getRawValue().senha).subscribe({
      next: () => void this.router.navigate(['/login']),
      error: (erro: unknown) => {
        this.excluindo.set(false);
        this.erroExclusao.set(
          statusDoErro(erro) === 401
            ? 'Senha incorreta.'
            : mensagemDeErro(erro, 'Não foi possível excluir a conta. Tente de novo.'),
        );
      },
    });
  }

  protected trocar(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { senha_atual, nova_senha } = this.form.getRawValue();
    this.enviando.set(true);
    this.erro.set(null);
    this.sucesso.set(false);

    this.auth.trocarSenha({ senha_atual, nova_senha }).subscribe({
      next: () => {
        this.enviando.set(false);
        this.sucesso.set(true);
        this.form.reset();
      },
      error: (erro: unknown) => {
        this.enviando.set(false);
        this.erro.set(mensagemDeErro(erro, 'Não foi possível trocar a senha. Tente de novo.'));
      },
    });
  }

  protected invalido(campo: 'senha_atual' | 'nova_senha' | 'confirmacao'): boolean {
    const controle = this.form.controls[campo];
    return controle.invalid && controle.touched;
  }

  protected senhasDiferentes(): boolean {
    const confirmacao = this.form.controls.confirmacao;
    return confirmacao.valid && confirmacao.touched && this.form.hasError('senhasDiferentes');
  }
}
