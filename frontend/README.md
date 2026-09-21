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
  core/api/      contratos (interfaces) e clientes HTTP de cada recurso
  core/format/   datas em pt-BR
  core/http/     tradução de erro do FastAPI para mensagem de tela
  core/mock/     dados de demonstração + implementações mock dos serviços
  layout/shell/  moldura das telas autenticadas (nav lateral de 232px)
  features/      telas
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

## Dados de demonstração (mock)

Três telas — **Início**, **Resultados** e **Comentários** — mostram dados
fictícios. Elas dependem de `ANALISES_SENTIMENTO`, `TEMAS` e `COMENTARIO_TEMA`,
que só existem depois que o worker de inferência rodar. Enquanto isso, cada uma
exibe o selo **"Dados de demonstração"**.

O resto da aplicação (login, cadastro, modelos de análise, execuções) já fala
com a API real — o mock cobre só os três recursos de análise.

### Como funciona

Cada recurso tem uma classe abstrata em `core/api/` com duas implementações:

| Recurso               | Abstrato             | Real                     | Mock                     |
| --------------------- | -------------------- | ------------------------ | ------------------------ |
| Painel (Início)       | `PainelService`      | `PainelHttpService`      | `PainelMockService`      |
| Resultado de execução | `ResultadosService`  | `ResultadosHttpService`  | `ResultadosMockService`  |
| Comentários           | `ComentariosService` | `ComentariosHttpService` | `ComentariosMockService` |

As telas injetam a classe abstrata e não sabem qual implementação receberam.
A escolha é **uma linha em `src/app/app.config.ts`**:

```ts
provideDadosDeDemonstracao(); // hoje: mock nas três telas + selo aceso
provideDadosReais(); // depois: API real, selo apagado
```

O mesmo provider define o token `DADOS_DE_DEMONSTRACAO`, que o componente
`selo-demo` lê. Não existe estado em que a tela mostre número fictício sem o
aviso, nem dado real marcado como fictício — há teste para as duas pontas em
`features/painel/selo-demo.spec.ts`.

O mock responde por `Observable` com atraso sorteado entre 300 e 800 ms
(`core/mock/latencia.ts`), para os estados de carregamento serem exercitados em
desenvolvimento. Ele também filtra e pagina de verdade sobre a amostra, em vez
de devolver sempre a mesma página.

### Endpoints que precisam existir para desligar cada mock

Os contratos já estão escritos em `core/api/*.models.ts`, com o nome de cada
campo igual ao da coluna. Implementar estes três endpoints e trocar o provider
é tudo o que falta.

#### 1. `GET /api/v1/painel` → `ResumoPainel`

Desliga o mock da tela **Início**. Definido em `core/api/painel.models.ts`.

Monta, para o usuário do token: a última execução concluída (`destaque`), a
lista de modelos com o status da execução mais recente, os totais e a versão do
classificador em uso (`VERSOES_MODELO` com `status = 'ativo'`).

#### 2. `GET /api/v1/execucoes/{id}/resultado` → `ResultadoExecucao`

Desliga o mock da tela **Resultados**. Definido em `core/api/resultados.models.ts`.

Agrega, para uma execução do usuário: contagem de `ANALISES_SENTIMENTO` por
`sentimento` (geral, por vídeo e por tema), somas de `VIDEOS` para o alcance,
`TEMAS` com `palavras_chave`, três comentários representativos e a
`VERSOES_MODELO` usada. Responde 404 quando a execução não é do usuário, como
os demais endpoints de execução.

Junto vai `GET /api/v1/execucoes/resultados` → `ResultadoDisponivel[]`, a lista
de execuções concluídas que alimenta `/resultados`.

#### 3. `GET /api/v1/execucoes/{id}/comentarios` → `PaginaComentarios`

Desliga o mock da tela **Comentários**. Definido em `core/api/comentarios.models.ts`.

Query string: `busca`, `id_tema`, `id_video`, `sentimento`, `pagina`, `tamanho`.
Cada item junta `COMENTARIOS` + `ANALISES_SENTIMENTO` + o vídeo + os temas de
`COMENTARIO_TEMA` com o `peso`.

Detalhe que muda o resultado: `contagem_por_sentimento` é calculada **sem** o
filtro de sentimento — os chips "Positivo · 160 / Neutro · 198" precisam
continuar visíveis depois que um deles é escolhido.

### Três coisas que o banco ainda não tem

Estas apareceram ao escrever os contratos. Nenhuma bloqueia o mock, todas
bloqueiam o endpoint real:

1. **`ANALISES_SENTIMENTO.confianca` não existe.** O design pede o selo
   "Revisão sugerida" em classificação de baixa confiança (`Comentarios.png`), e
   isso exige o score do modelo persistido. Ou entra uma coluna
   `confianca REAL` por migration, ou o campo sai do contrato e o selo some.
   O contrato hoje declara `confianca: number | null` marcado com este aviso.

2. **Consumo de cota da YouTube API não é registrado.** O cartão "Cota do
   YouTube hoje" (`Home.png`) não tem fonte: o worker de coleta gasta cota, mas
   não contabiliza em lugar nenhum. `ResumoPainel.cota_youtube` é anulável
   justamente por isso — sem a fonte, o endpoint devolve `null` e o cartão não
   aparece.

3. **Não há endpoint de relatório.** O botão "Baixar relatório" do
   `Dashboard.png` está na tela, desabilitado, esperando por ele.

### Sobre os números da demonstração

Os agregados (3.892 comentários, 1,5 mi de visualizações, contagem por tema)
têm a ordem de grandeza de uma execução real, dentro do escopo de 500 a 5.000
comentários do projeto. Já a **lista** de comentários é uma amostra de algumas
dezenas de textos escritos à mão — por isso a tela de Comentários mostra
"14 comentários no tema Preço" onde o Dashboard mostra 761. É a amostra que se
pode paginar de verdade; o número grande é o agregado.

Os textos imitam o que a coleta real traz: português informal, gíria, ironia,
erro de digitação e emoji. Comentário limpo demais esconderia justamente os
casos em que a classificação erra — o comentário irônico "nossa que entrega
RÁPIDA hein, só 3 semanas pra chegar 👏👏" está lá de propósito, com confiança
baixa e selo de revisão.

## Antes de publicar

`angular.json` → `build.options.security.allowedHosts` hoje tem só
`localhost` e `127.0.0.1`. É a proteção contra SSRF do Angular 21: o SSR
recusa requisições cujo header `Host` não esteja na lista e cai para
renderização no cliente. **O domínio de produção precisa entrar nessa lista**,
senão o SSR não funciona no ar.
