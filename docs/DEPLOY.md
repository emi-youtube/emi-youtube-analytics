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
| **Dois App Services** (um API, um runner) | **O problema não é custo.** Dois apps no MESMO App Service Plan dividem a instância sem cobrança extra — o que se paga é o plano, não o app. O que inviabiliza é outra coisa: um App Service sem rota HTTP não tem como responder ao *health check* da plataforma, e o Azure recicla o contêiner por considerá-lo insalubre. Um consumidor de fila puro seria reiniciado em laço. (E os dois dividindo uma B1 disputariam a mesma memória de qualquer forma.) |
| **App Service + WebJob contínuo** | **Inviável.** WebJobs só existem no App Service **Windows**; este backend é Python/Linux. |
| **App Service + Container Instance** | Aí sim há custo novo, fora do plano, e mais um serviço para operar — contra o CLAUDE.md Seção 10 (a fila é uma tabela justamente para não pagar infraestrutura). |
| **Um App Service, dois processos** ✅ | Escolhido. O runner fica ao lado de um processo que responde HTTP, então a plataforma vê o contêiner saudável e não o recicla. Cabe com folga na B1 e não há serviço intermediário para coordenar. |

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

### Quem instala as dependências: o servidor

O GitHub publica **código-fonte**; quem roda o `pip install` é o **Oryx**, no App
Service. Três razões:

1. `numpy`, `scipy` e `scikit-learn` são rodas **binárias**. Instaladas pela
   plataforma, são as da imagem do App Service; instaladas no runner do GitHub,
   a compatibilidade passaria a ser torcida.
2. O Oryx cria e ativa o virtualenv (`antenv`). O `startup.sh` sobe dois
   processos chamando `python` — com o `antenv` ativo isso funciona sem mexer em
   `PYTHONPATH` em lugar nenhum.
3. O envio fica em ~2 MB em vez de ~250 MB.

O preço é que as App settings precisam dizer a mesma coisa que o workflow
(seção A6). Mandar um pacote já montado **e** pedir build ao servidor foi o que
derrubou o primeiro deploy: cada lado assumiu que o outro tinha feito o trabalho.

### O pacote: por que `backend/` sozinho não sobe

`backend/requirements.txt` instala dois pacotes que moram **na raiz do
repositório**: `preprocessamento/` e `lexico/` (CLAUDE.md Seção 3 — o que treino
e inferência precisam executar igual mora num terceiro pacote). Com `backend/`
como raiz da aplicação, esses caminhos não existem no servidor.

E eles estão declarados com `-e` (editável), que é o certo para desenvolvimento
e errado para deploy: editável grava no `site-packages` um **ponteiro para a
pasta de origem**, que no servidor é o diretório temporário onde o Oryx monta o
app antes de copiá-lo. O ponteiro fica apontando para o vazio e o import quebra
em **produção**, não no build — o deploy "dá certo" e o app morre ao subir.

`backend/scripts/montar_pacote.sh` monta um pacote autocontido: leva os dois
compartilhados para dentro dele e tira o `-e` da cópia que vai para o servidor.
O `requirements.txt` do repositório não muda — continua editável para quem
desenvolve.

O mesmo script roda no workflow e na conferência local, de propósito: se a prova
montasse o pacote de outro jeito, não provaria nada sobre o que é publicado. O
workflow ainda instala o pacote num ambiente limpo e falha se algum
compartilhado tiver virado ponteiro em vez de cópia.

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

**Decidido:** a lista tem **só o domínio de produção**. As URLs de *preview* da
Vercel mudam a cada deploy e não serão usadas, então não há motivo para afrouxar
a proteção com `"*"` — o que o próprio Angular só considera aceitável quando
outra camada valida o `Host`. Preview responde 400; é o esperado.

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
   **Operating System** = `Linux`; **Region** = `Brazil South`, para ficar perto
   do Supabase em `sa-east-1`.

   > **Se a assinatura de estudante recusar a região** (acontece: a Azure for
   > Students não libera todas as regiões, e algumas ficam sem capacidade para o
   > plano Basic), use a permitida mais próxima — em ordem de preferência:
   > `South Central US`, `East US 2`, `East US`. A consequência é só latência a
   > mais entre a API e o banco; nada no código depende da região. O importante
   > é NÃO mudar a região do Supabase, que é onde os dados estão.
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
   | `SCM_DO_BUILD_DURING_DEPLOYMENT` | `1` |
   | `ENABLE_ORYX_BUILD` | `true` |

   > **Os dois primeiros decidem QUEM instala as dependências, e precisam
   > concordar com o workflow.** O fluxo escolhido é: o GitHub publica
   > código-fonte, e o **Oryx instala no servidor** — é o que garante que as
   > rodas binárias de `numpy`, `scipy` e `scikit-learn` sejam as da imagem do
   > App Service, e é o Oryx quem cria o virtualenv (`antenv`) que o
   > `startup.sh` usa para subir os dois processos.
   >
   > **`WEBSITE_RUN_FROM_PACKAGE` não pode existir.** Se estiver na lista,
   > **apague**: ela monta o `wwwroot` como pacote só-leitura, e aí o Oryx não
   > tem onde construir. Foi a combinação de "pacote pronto" com "build no
   > servidor" que derrubou o primeiro deploy.
   >
   > Nenhum destes valores entra no repositório nem na imagem. O `.env` está no
   > `.gitignore` e não é publicado.

7. **NÃO use o Deployment Center.** O workflow que ele gera publica a pasta
   `backend/` como está, e ela sozinha não é instalável: o `requirements.txt`
   dela instala `preprocessamento/` e `lexico/`, que ficam na raiz do
   repositório. O deploy subiria sem os dois. O repositório já traz o workflow
   certo em `.github/workflows/deploy-backend.yml`, que monta um pacote
   autocontido. Os passos 8 a 10 o ligam ao seu App Service.

8. **Baixe o perfil de publicação.** No App Service, barra superior →
   **Download publish profile** (se não estiver visível, está em **⋯ / More**).
   Baixa um arquivo `.PublishSettings`. É um XML com credenciais — trate como
   senha: não abra em chat, não commite.

   > Se o botão estiver desabilitado, vá em **Configuration → General settings**
   > e ponha **SCM Basic Auth Publishing Credentials** = `On`. Contas novas do
   > Azure vêm com isso desligado por padrão.

9. **Cadastre o perfil como segredo do GitHub.** No repositório →
   **Settings → Secrets and variables → Actions → New repository secret**:

   | Campo | Valor |
   |---|---|
   | **Name** | `AZURE_WEBAPP_PUBLISH_PROFILE` |
   | **Secret** | abra o `.PublishSettings` num editor de texto e cole o **conteúdo inteiro do XML** |

   O nome tem de ser exatamente esse — é o que o workflow lê. O GitHub mascara
   segredos no log, então ele não vaza nas execuções.

10. **Ajuste o nome do app no workflow.** Em
    `.github/workflows/deploy-backend.yml`, troque `NOME_DO_APP` pelo nome do
    App Service do passo A3. Commit na `main` dispara o primeiro deploy; dá para
    disparar à mão em **Actions → Deploy do backend → Run workflow**.

11. Depois do primeiro deploy, abra **Log stream** e confirme três linhas:
    `[sentilex] ok:`, a migration do Alembic e
    `workers iniciados etapas=coleta,inferencia,topicos`.

12. Teste a API: abra `https://<nome>.azurewebsites.net/api/v1/health` — tem de
    responder `{"status":"ok","database":"connected"}`.

### B. Azure — a migration do reaper

Nada a fazer: a migration `0009` roda sozinha no arranque (passo 2 do
`startup.sh`), antes de qualquer processo atender. Se preferir aplicá-la antes
do primeiro deploy, é `alembic upgrade head` apontando para o mesmo banco.

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

## 4. Quando o site sobe 503

Estas três linhas no **Log stream** aparecem juntas e são o mesmo problema — o
Oryx não construiu o app:

```
Could not find build manifest file at '/home/site/wwwroot/oryx-manifest.toml'
Could not find virtual environment directory /home/site/wwwroot/antenv
bash: /home/site/wwwroot/startup.sh: No such file or directory
```

São duas causas possíveis, e o `startup.sh` agora distingue as duas: ele imprime
`[startup] python:` e, se faltar dependência, diz exatamente quais App settings
conferir.

**Causa 1 — os dois fluxos brigando.** O deploy manda um pacote e as App
settings pedem build no servidor, ou vice-versa. Confira que estão assim:

| Setting | Valor |
|---|---|
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `1` |
| `ENABLE_ORYX_BUILD` | `true` |
| `WEBSITE_RUN_FROM_PACKAGE` | **não deve existir** |

**Causa 2 — o zip com um nível a mais.** Se o arquivo for montado a partir da
pasta (`zip -r pacote.zip pacote`) em vez de a partir de dentro dela, tudo fica
sob `pacote/` e o `wwwroot` fica sem `startup.sh` na raiz — que é literalmente a
terceira linha do log. O workflow monta o zip de dentro da pasta e **falha** se
`startup.sh` não estiver na raiz, então isto não deve voltar; a nota fica para
quem publicar à mão.

Para publicar à mão, o jeito certo é:

```bash
bash backend/scripts/montar_pacote.sh pacote
cd pacote && zip -qr ../pacote.zip . && cd ..   # de DENTRO da pasta
```

## 5. O que fica de fora desta etapa

- **Cota do YouTube não é registrada**; o cartão do painel fica oculto.
- **Preview da Vercel não renderiza no servidor** enquanto a decisão de
  `allowedHosts` não for tomada (seção 2).
- **Um App Service só** significa que um deploy derruba API e runner juntos por
  alguns segundos. O reaper cobre os jobs que estiverem no meio do caminho.
