import { Marked, Tokens } from 'marked';

/** "4. Dados que coletamos" -> "4-dados-que-coletamos": âncora estável para links. */
export function ancora(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Âncora da Política de Privacidade: a seção 4 dos Termos (`/privacidade` pula para ela). */
export const ANCORA_PRIVACIDADE = 'privacidade';

/**
 * Markdown -> HTML, com `id` em cada título para os links de âncora.
 *
 * O primeiro título de nível 2 que começa por "4" recebe também o id
 * `privacidade`, de modo que `/privacidade` funcione sem depender do texto exato
 * do título — quem edita o termo pode renomear a seção sem quebrar o link.
 *
 * Só para texto NOSSO, versionado no repositório: o componente marca o HTML como
 * confiável (o sanitizador do Angular tiraria os `id`). Nunca passe por aqui
 * texto vindo de usuário ou da API.
 */
export function renderizarMarkdown(markdown: string): string {
  let privacidadeMarcada = false;
  const marked = new Marked({
    gfm: true,
    renderer: {
      heading(this: { parser: { parseInline(tokens: Tokens.Generic[]): string } }, titulo) {
        const conteudo = this.parser.parseInline(titulo.tokens);
        const id = ancora(titulo.text);
        if (!privacidadeMarcada && titulo.depth === 2 && /^\s*4\b/.test(titulo.text)) {
          privacidadeMarcada = true;
          return `<h2 id="${ANCORA_PRIVACIDADE}"><span id="${id}"></span>${conteudo}</h2>\n`;
        }
        return `<h${titulo.depth} id="${id}">${conteudo}</h${titulo.depth}>\n`;
      },
    },
  });
  return marked.parse(markdown, { async: false });
}
