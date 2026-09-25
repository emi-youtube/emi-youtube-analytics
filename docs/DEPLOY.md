# Deploy — Azure for Students (backend) + Vercel (frontend)

Os arquivos de deploy estão no repositório; o que **não** está, e não pode estar,
são os segredos. Este documento é o passo a passo do que se configura nos
painéis, e o registro das decisões que levaram a estes arquivos.

---

## 1. Backend: por que API e runner no MESMO App Service

A B1 tem 1,75 GB e o crédito do Azure for Students é finito. Quatro arranjos
foram considerados:

| Arranjo | Veredito |
|---|---|
| **Dois App Services** (um API, um runner) | Dobra o custo para rodar dois processos que somados não passam de ~700 MB. Pior: App Service espera responder HTTP, e um serviço que só consome fila falharia o *health check* e seria reciclado em laço. |
| **App Service + WebJob contínuo** | **Inviável.** WebJobs só existem no App Service **Windows**; este backend é Python/Linux. |
| **App Service + Container Instance** | Mais um serviço para pagar e operar, contra o CLAUDE.md Seção 10 (a fila é uma tabela justamente para não pagar infraestrutura). |
| **Um App Service, dois processos** ✅ | Escolhido. Cabe com folga, custa uma instância, e a fila já é uma tabela — não há serviço intermediário para coordenar. |

**Como os dois convivem** (`backend/startup.sh`): a API fica em **primeiro
plano**, porque é o processo que o Azure monitora por HTTP e é dele que o ciclo
de vida do contêiner deve depender. O runner fica **supervisionado em segundo
plano**, com espera crescente entre reinícios — uma queda dele não derruba a API,
e enquanto ele volta o *reaper* devolve à fila o job que ele estava processando.

**Memória esperada:** uvicorn ~150 MB; runner com `scikit-learn`, `numpy`,
`scipy` e o SentiLex carregado ~500 MB. Sobra folga na B1. Não há `torch` nem
`transformers`: o classificador em produção é o léxico, que é stdlib pura.

**"Always On" é obrigatório.** Sem ele o App Service descarrega o contêiner
ocioso e o runner simplesmente para de existir até a próxima requisição HTTP.
Está disponível a partir do plano Basic, que é o caso da B1.

### O arquivo do SentiLex

Não está no git (dado de terceiro, 6,9 MB — ver `ml/lexico/README.md`).
`backend/scripts/baixar_sentilex.sh` o baixa no arranque para `/home/data/`, que
é o único caminho que **sobrevive a restart** no App Service, e **confere o
sha256** antes de promover o arquivo ao caminho definitivo. Se o hash não bater,
o script falha com a diferença impressa em vez de deixar um arquivo errado no
lugar — que faria o worker recusar subir a cada reinício, sem se recuperar
sozinho.

Nas execuções seguintes o script encontra o arquivo já correto e não baixa nada.

---

## 2. Frontend: o que foi VERIFICADO sobre Angular SSR na Vercel

Isto foi conferido antes de assumir, e o resultado mudou o desenho.

**A Vercel não tem preset de framework para Angular SSR.** Angular não aparece na
matriz de infraestrutura suportada da documentação deles. O caminho é o padrão da
comunidade: uma função serverless que chama o `reqHandler` que o `src/server.ts`
já exporta.

- `frontend/api/ssr.mjs` — a ponte. `.mjs` porque o `package.json` não declara
  `"type": "module"` e declarar mudaria a interpretação de todo `.js` do projeto.
- `frontend/vercel.json` — reescreve `/api/v1/*` para o Azure **primeiro**, e só
  então manda o resto para a função de SSR. A ordem importa: as regras são
  avaliadas em sequência e a primeira que casa vence.

A função se chama `ssr` e não `index` de propósito: em `api/index.mjs` ela
responderia em `/api`, o mesmo prefixo da nossa API, e a separação passaria a
depender só da ordem das regras.

### allowedHosts — três comportamentos medidos

Medidos contra o bundle de produção rodando local, porque o comportamento real é
mais severo do que a documentação interna do projeto dizia:

1. **Host fora da lista recebe `HTTP 400`**, não renderização no cliente. O corpo
   é `Header "host" with value "..." is not allowed.`, sem HTML. Domínio errado
   não degrada a página: derruba o site inteiro.
2. **A entrada precisa estar em minúsculas.** O Angular compara contra o host já
   normalizado. O header da requisição pode vir em qualquer caixa.
3. **Não há curinga.** `.vercel.app` na lista **não** libera
   `emi-git-branch-x.vercel.app` — medido, dá 400.

**Consequência a decidir:** as URLs de *preview* da Vercel mudam a cada deploy,
então **preview não vai funcionar com SSR**. Duas saídas, e a escolha é da
equipe:

- **(a) aceitar** que só o domínio de produção renderiza no servidor — nenhuma
  perda de segurança, previews ficam quebrados;
- **(b) usar `"*"`** na lista. O próprio Angular considera isso aceitável
  "quando a validação dos headers `Host` e `X-Forwarded-Host` é feita em outra
  camada, como um load balancer ou proxy reverso". A Vercel é essa camada — ela
  só roteia os próprios domínios para a função. Ainda assim é afrouxar uma
  proteção, e por isso não foi feito sem decisão.

**Armadilha local:** o cache do Angular (`.angular/cache`) reaproveita o
manifesto e serve a lista antiga. Ao mexer em `allowedHosts`, apague o cache
antes de acreditar no teste. (Na Vercel cada build é limpo.)

---

## 3. Passo a passo — o que VOCÊ precisa fazer

Nada aqui pede segredo no chat. Todos os valores são digitados direto nos
painéis.

### A. Azure — criar e configurar o App Service

1. **Portal do Azure → Create a resource → Web App.**
2. Preencha: **Publish** = `Code`; **Runtime stack** = `Python 3.11`;
   **Operating System** = `Linux`; **Region** = a mesma do banco
   (`Brazil South`, para ficar perto do Supabase em `sa-east-1`).
3. Em **Pricing plan**, escolha **B1**. Anote o **nome do app** — ele vira
   `<nome>.azurewebsites.net` e você vai precisar dele no passo D2.
4. Criado o recurso, abra **Settings → Configuration → General settings** e
   ponha em **Startup Command**:
   ```
   bash /home/site/wwwroot/startup.sh
   ```
5. Ainda em **General settings**, ligue **Always On** = `On`.
   Sem isso o runner para quando o site fica ocioso.
6. Vá em **Settings → Environment variables → App settings** e crie, uma a uma
   (**Add**, nome e valor, e **Apply** no fim):

   | Nome | Valor |
   |---|---|
   | `DATABASE_URL` | a string do Supabase (Session pooler, porta 5432), com o prefixo `postgresql+asyncpg://` |
   | `JWT_SECRET_KEY` | gere com `openssl rand -hex 32` e cole |
   | `YOUTUBE_API_KEY` | a chave do Google Cloud |
   | `SENTILEX_PATH` | `/home/data/SentiLex-flex-PT02.txt` |
   | `APP_ENV` | `production` |
   | `CORS_ORIGINS` | o domínio da Vercel, ex.: `https://emi-youtube-analytics.vercel.app` |
   | `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` |

   > `SCM_DO_BUILD_DURING_DEPLOYMENT` é o que faz o Azure instalar o
   > `requirements.txt`. Sem ele o app sobe sem dependência nenhuma.
   >
   > Nenhum destes valores entra no repositório nem na imagem. O `.env` está no
   > `.gitignore` e não é publicado.

7. **Deployment Center → GitHub**, autorize, e selecione o repositório e a
   branch `main`. Em **Build provider** use **GitHub Actions**. Confirme que o
   *workflow* gerado aponta para a pasta `backend` como raiz do app — se não
   apontar, me avise que eu ajusto o arquivo.

8. Depois do primeiro deploy, abra **Log stream** e confirme três linhas:
   `[sentilex] ok:`, a migration do Alembic e
   `workers iniciados etapas=coleta,inferencia,topicos`.

9. Teste a API: abra `https://<nome>.azurewebsites.net/api/v1/health` — tem de
   responder `{"status":"ok","database":"connected"}`.

### B. Azure — aplicar a migration do reaper

A migration `0009` roda sozinha no arranque (passo 2 do `startup.sh`). Se
preferir rodar antes, é `alembic upgrade head` apontando para o mesmo banco.

### C. Vercel — importar o projeto

1. **vercel.com → Add New → Project → Import Git Repository**, escolha o repo.
2. Em **Root Directory**, selecione **`frontend`**.
3. Em **Framework Preset**, escolha **Other**. *(Não escolha "Angular": aquele
   preset assume saída estática e ignora o SSR.)*
4. Deixe **Build Command** e **Output Directory** como estão — o `vercel.json`
   já define os dois.
5. **Deploy.** Anote o domínio gerado (`<algo>.vercel.app`).

### D. Amarrar os dois — dois valores que só existem depois do deploy

1. **No `angular.json`** (repositório), troque
   `substitua-pelo-dominio.vercel.app` pelo domínio real **em minúsculas**, em
   `projects.emi-frontend.architect.build.options.security.allowedHosts`.
2. **No `frontend/vercel.json`**, troque
   `SUBSTITUA-PELO-APP-SERVICE.azurewebsites.net` pelo nome do App Service do
   passo A3.
3. Faça commit das duas trocas e deixe a Vercel publicar de novo.
4. **No Azure**, confirme que `CORS_ORIGINS` tem o domínio real da Vercel.

> Os dois são *placeholders* de propósito: nenhum dos dois valores existe antes
> de os recursos serem criados, e chutá-los deixaria um domínio errado no
> repositório — que, no caso do `allowedHosts`, derruba o site com 400.

### E. Conferência final

1. Abra `https://<dominio>.vercel.app` — a página tem de vir renderizada
   (desligue o JavaScript e o conteúdo ainda aparece; é o SSR funcionando).
2. Faça login. Se a tela carrega mas nenhuma chamada responde, o rewrite do
   `/api/v1` está errado — confira o passo D2.
3. Se a página vier em branco com erro 400, é o `allowedHosts` — confira D1, em
   minúsculas.
4. Dispare uma execução pequena e acompanhe pelo **Log stream** do Azure.

---

## 4. O que fica de fora desta etapa

- **Cota do YouTube não é registrada**; o cartão do painel fica oculto.
- **Preview da Vercel não renderiza no servidor** enquanto a decisão de
  `allowedHosts` não for tomada (seção 2).
- **Um App Service só** significa que um deploy derruba API e runner juntos por
  alguns segundos. O reaper cobre os jobs que estiverem no meio do caminho.
