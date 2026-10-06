import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';

import texto from '../../../assets/legal/termos-v1.md';
import { ANCORA_PRIVACIDADE, ancora, renderizarMarkdown } from './markdown';
import { Termos } from './termos';

describe('renderizarMarkdown', () => {
  it('dá id a cada título e marca a seção 4 como a Política de Privacidade', () => {
    const html = renderizarMarkdown(
      '# Termos\n\n## 1. Objeto\n\ntexto\n\n## 4. Privacidade e dados\n\n- item\n\n## 4b. Outra',
    );

    expect(html).toContain('<h1 id="termos">Termos</h1>');
    expect(html).toContain('<h2 id="1-objeto">1. Objeto</h2>');
    expect(html).toContain(`<h2 id="${ANCORA_PRIVACIDADE}">`);
    // Só a primeira seção "4" recebe a âncora: ids repetidos quebrariam o link.
    expect(html.match(new RegExp(`id="${ANCORA_PRIVACIDADE}"`, 'g'))).toHaveLength(1);
    expect(html).toContain('<li>item</li>');
  });

  it('âncora sem acento nem pontuação', () => {
    expect(ancora('4. Política de Privacidade — Dados')).toBe('4-politica-de-privacidade-dados');
  });
});

describe('Termos', () => {
  it('renderiza o texto legal versionado, com links para as duas âncoras', () => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(Termos);
    fixture.detectChanges();

    const artigo: HTMLElement = fixture.nativeElement.querySelector('[data-testid="texto-legal"]');
    expect(artigo.querySelector('h1')).not.toBeNull();
    const links = Array.from(
      fixture.nativeElement.querySelectorAll('.legal__topo a') as NodeListOf<HTMLAnchorElement>,
    ).map((a) => a.getAttribute('href'));
    expect(links).toEqual(['/', '/termos', '/privacidade']);
    // Os ids sobrevivem à renderização (o sanitizador os tiraria).
    expect(artigo.querySelector('h1')?.id).not.toBe('');
  });

  // Pulado enquanto termos-v1.md for o marcador de lugar (o texto aprovado ainda não
  // entrou no repositório); passa a valer sozinho quando o arquivo for trocado.
  it.skipIf(texto.includes('TEXTO PENDENTE'))(
    'o texto vigente tem a seção 4, alvo de /privacidade',
    () => {
      TestBed.configureTestingModule({ providers: [provideRouter([])] });
      const fixture = TestBed.createComponent(Termos);
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector(`#${ANCORA_PRIVACIDADE}`)).not.toBeNull();
    },
  );
});
