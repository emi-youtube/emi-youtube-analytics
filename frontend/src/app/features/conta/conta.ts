import { DOCUMENT } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { ContaService } from '../../core/api/conta.service';

import { AuthService } from '../../core/auth/auth.service';
import { SENHA_MINIMA, senhasConferem } from '../../core/auth/senha';
import { mensagemDeErro, statusDoErro } from '../../core/http/api-error';

/**
 * Minha conta: dados de quem está logado, troca de senha e os direitos do
 * titular (ADR-012) — baixar os dados e excluir a conta.
 * Consome `POST /api/v1/auth/trocar-senha`, `GET /api/v1/conta/meus-dados` e
 * `DELETE /api/v1/conta`.
 */
@Component({
  selector: 'app-conta',
  imports: [ReactiveFormsModule],
  templateUrl: './conta.html',
  styleUrls: ['../painel/painel.css', './conta.css'],
})
export class Conta {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly conta = inject(ContaService);
  private readonly router = inject(Router);
  private readonly documento = inject(DOCUMENT);

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

  /** O texto da zona de perigo muda: o dono único leva a empresa junto. */
  protected readonly ehDono = computed(() => this.usuario()?.papel_empresa === 'dono');

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
