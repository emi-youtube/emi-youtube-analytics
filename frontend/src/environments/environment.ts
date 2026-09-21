/** Produção: a URL da API é injetada no build (Vercel) — nunca aponta para localhost. */
export const environment = {
  production: true,
  apiBaseUrl: '/api/v1',
};
