import { DOCUMENT, isPlatformBrowser } from '@angular/common';
import {
  Component,
  PLATFORM_ID,
  ViewEncapsulation,
  afterNextRender,
  inject,
  input,
} from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';

import texto from '../../../assets/legal/termos-v1.1.md';
import { ANCORA_PRIVACIDADE, renderizarMarkdown } from './markdown';

/**
 * Termos de Uso e Política de Privacidade (ADR-012). Pública: quem ainda não tem
 * conta precisa ler antes de aceitar no cadastro.
 *
 * Uma página só, com âncoras: o texto é um documento único (`termos-v1.1.md`), e a
 * Política é a seção 4 em diante. `/privacidade` é esta mesma página rolada até
 * ela — dois arquivos obrigariam a manter a numeração e a versão em dobro.
 *
 * O markdown entra no bundle como texto (loader `.md` no angular.json): o SSR já
 * entrega a página renderizada, sem requisição.
 */
@Component({
  selector: 'app-termos',
  imports: [RouterLink],
  templateUrl: './termos.html',
  styleUrl: './termos.css',
  // O HTML do markdown não recebe os atributos do encapsulamento emulado.
  encapsulation: ViewEncapsulation.None,
})
export class Termos {
  /** `data` da rota: `privacidade` rola até a seção 4. */
  readonly secao = input<'termos' | 'privacidade'>('termos');

  /**
   * Confiável sem sanitizar, de propósito: o sanitizador do Angular remove os
   * `id` dos títulos, e sem eles `/privacidade` não acha a seção 4. A fonte é
   * SÓ o arquivo versionado no repositório, empacotado no build — nada vindo de
   * usuário ou da API passa por aqui.
   */
  protected readonly html = inject(DomSanitizer).bypassSecurityTrustHtml(renderizarMarkdown(texto));

  constructor() {
    const documento = inject(DOCUMENT);
    if (!isPlatformBrowser(inject(PLATFORM_ID))) {
      return;
    }
    afterNextRender(() => {
      if (this.secao() === 'privacidade') {
        documento.getElementById(ANCORA_PRIVACIDADE)?.scrollIntoView();
      }
    });
  }
}
