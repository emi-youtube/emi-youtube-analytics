// Ponte entre a Vercel e o servidor SSR do Angular.
//
// POR QUE ISTO EXISTE: a Vercel NAO tem preset de framework para Angular SSR --
// Angular nem aparece na matriz de infraestrutura suportada da documentacao
// deles. O padrao da comunidade e o que esta aqui: uma funcao serverless que
// importa o `reqHandler` que o `src/server.ts` ja exporta (o Angular o gera para
// o dev-server e para Cloud Functions) e entrega a requisicao a ele.
//
// POR QUE `.mjs` E NAO `.js`: o `package.json` nao declara `"type": "module"`,
// e declarar mudaria a interpretacao de todo arquivo .js do projeto, incluindo os
// de configuracao do Angular. A extensao .mjs resolve so para este arquivo.
//
// POR QUE `ssr` E NAO `index`: uma funcao em `api/index.js` responderia em
// `/api`, e `/api/v1/*` e o caminho da NOSSA API no Azure. Manter os dois no
// mesmo prefixo dependeria so da ordem das regras de rewrite -- funciona, mas um
// dia alguem reordena o `vercel.json` e o front passa a servir HTML no lugar do
// JSON da API. Com o nome separado, a colisao nao existe.
export default async function handler(req, res) {
  const { reqHandler } = await import('../dist/emi-frontend/server/server.mjs');
  return reqHandler(req, res);
}
