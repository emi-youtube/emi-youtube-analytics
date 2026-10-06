/**
 * Arquivos `.md` entram no bundle como texto (`loader` no angular.json). É assim
 * que o texto dos Termos chega ao SSR sem requisição HTTP.
 */
declare module '*.md' {
  const conteudo: string;
  export default conteudo;
}
