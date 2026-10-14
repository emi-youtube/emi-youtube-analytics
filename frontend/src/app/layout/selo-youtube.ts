import { Component, computed, input } from '@angular/core';

/** Endereço padrão: o próprio YouTube, para as telas que não mostram um vídeo específico. */
export const YOUTUBE = 'https://www.youtube.com';

/**
 * Selo "Developed with YouTube", exigido pelas diretrizes de marca dos YouTube API Services.
 *
 * As diretrizes pedem o logo oficial perto de onde os dados da API aparecem, clicável e com
 * link para conteúdo do YouTube, sem mudar as cores e sem ser o elemento mais destacado da
 * página. Os dois arquivos em `public/marca/` são os oficiais, só com a margem transparente
 * reduzida: o de texto escuro vai em fundo claro, o de texto branco em fundo escuro.
 */
@Component({
  selector: 'app-selo-youtube',
  template: `
    <a
      class="selo"
      [href]="href()"
      target="_blank"
      rel="noopener noreferrer"
      data-testid="selo-youtube"
      title="Abrir no YouTube"
    >
      <img [src]="arquivo()" alt="Developed with YouTube" width="160" height="24" />
    </a>
  `,
  styles: `
    :host {
      display: inline-flex;
    }

    .selo {
      display: inline-flex;
      border-radius: 4px;
    }

    .selo:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }

    img {
      display: block;
      height: 24px;
      width: auto;
    }
  `,
})
export class SeloYoutube {
  /** Para onde o selo leva: o vídeo analisado, quando houver um; senão, o YouTube. */
  readonly href = input<string>(YOUTUBE);
  /** A cor do fundo onde o selo está, que decide qual dos dois arquivos oficiais usar. */
  readonly fundo = input<'claro' | 'escuro'>('claro');

  protected readonly arquivo = computed(() =>
    this.fundo() === 'escuro'
      ? '/marca/developed-with-youtube-branco.png'
      : '/marca/developed-with-youtube-escuro.png',
  );
}
