/**
 * Produção.
 *
 * `apiBaseUrl` é RELATIVO de propósito, e nada o injeta no build — o comentário
 * anterior dizia que a Vercel injetava, e isso nunca foi verdade (card "URL da
 * API em produção"). Quem faz o caminho relativo chegar ao backend no Azure é o
 * REWRITE do `vercel.json`: `/api/v1/*` é reescrito para o App Service, do lado
 * do servidor da Vercel.
 *
 * Por que rewrite e não a URL absoluta do Azure aqui:
 * - para o navegador, front e API ficam na MESMA origem — não há CORS;
 * - o código Angular não muda nada;
 * - deixa a porta aberta para guardar o refresh token em cookie HttpOnly no
 *   futuro, sem precisar religar `allow_credentials` no CORS.
 *
 * Trocar o backend de endereço é editar o `vercel.json`, não este arquivo.
 */
export const environment = {
  production: true,
  apiBaseUrl: '/api/v1',
};
