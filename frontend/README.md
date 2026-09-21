# Frontend — Emi YouTube Analytics

Angular 21 com SSR (Angular Universal). Consome o FastAPI em `/api/v1`.

## Rodar

```bash
npm install
npm start                      # dev server em http://localhost:4200
```

O backend precisa estar de pé em `http://localhost:8000` — é o valor de
`apiBaseUrl` em `src/environments/environment.development.ts`. A origem
`http://localhost:4200` já está em `CORS_ORIGINS` no `.env` da raiz.

```bash
npm run build                  # build de produção (browser + server)
npm run serve:ssr:emi-frontend # sobe o SSR a partir de dist/
npm test                       # vitest
```

## Estrutura

```
src/app/
  core/auth/     sessão: serviço, interceptor, guards, storage do refresh token
  core/http/     tradução de erro do FastAPI para mensagem de tela
  layout/shell/  moldura das telas autenticadas (nav lateral de 232px)
  features/      telas — por enquanto só o login
src/styles.css   design tokens do design/DESIGN.md
```

## Sessão

O access token vive em memória (`AuthService`); só o refresh token é
persistido. Depois de um F5 o `authGuard` chama `ensureSession()`, que troca o
refresh por um access novo antes de liberar a rota. Durante o uso, o
`authInterceptor` renova no 401 e repete a requisição original — um refresh de
cada vez, mesmo com várias requisições falhando juntas.

No SSR os guards liberam a renderização (não há `localStorage` no servidor) e o
Angular roda os guards de novo no navegador, na hidratação. O HTML do servidor
é só o esqueleto, sem dado de usuário.

## Antes de publicar

`angular.json` → `build.options.security.allowedHosts` hoje tem só
`localhost` e `127.0.0.1`. É a proteção contra SSRF do Angular 21: o SSR
recusa requisições cujo header `Host` não esteja na lista e cai para
renderização no cliente. **O domínio de produção precisa entrar nessa lista**,
senão o SSR não funciona no ar.
