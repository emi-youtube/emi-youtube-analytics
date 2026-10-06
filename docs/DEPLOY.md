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

### Os pesos do BERTimbau — onde o modelo mora

O classificador de produção é o BERTimbau `bertimbau-emi 1.0.0`
(`backend/app/inferencia/bertimbau.py`). A pasta tem ~420 MB e **não vai para o
git**. As alternativas consideradas:

| opção | por que sim / por que não |
|---|---|
| **Hugging Face Hub, repositório privado** ✅ | Escolhida. É o lugar natural de um modelo `transformers`, é gratuito para repositório privado, e o download no arranque segue o mesmo padrão já provado do SentiLex. O token é de **leitura**, restrito a um repositório. |
| Commitar no git (LFS) | A cota gratuita do LFS é de 1 GB de banda por mês: dois ou três deploys a esgotariam. |
| Subir a pasta à mão para `/home` (Kudu/SSH) | Funciona e não precisa de conta extra, mas não é reproduzível: ninguém sabe dizer, meses depois, qual arquivo está lá. Serve de **plano B** se o Hub der problema — o worker só olha `BERTIMBAU_PATH` e o sha256, não sabe de onde veio a pasta. |
| Azure Blob Storage | Custaria crédito e mais uma conta de serviço para gerenciar, para resolver o mesmo que o Hub resolve de graça. |

**A integridade não depende da origem.** O sha256 de cada arquivo está versionado em
`backend/app/inferencia/bertimbau_manifesto.json`. O download
(`python -m app.inferencia.baixar_bertimbau`, chamado pelo `startup.sh`) baixa só o
que falta ou diverge, confere antes de promover, e o worker confere de novo ao
subir. Um repositório trocado ou um arquivo corrompido falham do mesmo jeito.

**Falhar não trava nada.** Se o download falhar, se a pasta estiver incompleta, se o
sha256 não bater ou se a `versao_preprocessamento` do cartão divergir da instalada,
o runner **cai para o léxico** e registra o motivo em WARNING no Log stream
(`BERTimbau indisponivel; usando o lexico como contingencia`). As análises feitas
assim apontam para a linha `lexico-sentilex` de `VERSOES_MODELO`, então o histórico
diz quem rotulou cada comentário. A troca só acontece na subida do worker.
Em `VERSOES_MODELO`, `ativo` é **o classificador que o worker carregou nesta subida**:
o runner marca a versão que subiu como `ativo` e todas as outras como `arquivado`, numa
transação só — é o que o painel mostra como modelo em uso, e em contingência diz léxico.

**Memória.** O runner com o BERTimbau em float32 fica em ~660 MB de pico
(`ml/medicao/relatorio_tempo_inferencia.json`), somando-se aos ~150 MB da API: cabe
na B1 (1,75 GB), com menos folga que antes.

**Publicar uma versão nova do modelo** é: subir a pasta para o repositório do Hub,
atualizar o manifesto (nome, versão e sha256 de cada arquivo — o `model_card.json`
precisa ter `nome_modelo` e `versao` iguais aos do manifesto), apontar
`BERTIMBAU_PATH` para uma pasta nova (`/home/modelos/<nome>-<versao>`) e fazer deploy.
A versão nova ganha linha própria em `VERSOES_MODELO` na subida do worker.

#### Uma vez: criar o repositório no Hub

1. Em huggingface.co, crie o repositório de **modelo** `emi-youtube/bertimbau-emi`
   (ou na conta pessoal), marcado como **Private**.
2. Suba a pasta `ml/modelos/bertimbau-2026-09-30/` inteira (os 7 arquivos do
   manifesto): `hf upload emi-youtube/bertimbau-emi ml/modelos/bertimbau-2026-09-30 .`
3. Crie um token **fine-grained** com permissão só de **leitura** nesse repositório.
   Ele vai para as App settings (passo A6), nunca para o repositório.

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
   bash startup.sh
   ```

   > **Relativo, não absoluto.** Com build automático o Oryx comprime a saída em
   > `output.tar.zst`, deixa o tarball no `wwwroot` e o extrai em `/tmp/<uid>` no
   > arranque — o app roda de lá, e o `wwwroot` fica só com o tarball e o
   > manifesto. A documentação do App Service é explícita: *"content is deployed
   > to and served from `/tmp/<uid>`, not under `/home/site/wwwroot`"* e *"All
   > commands must use paths that are relative to the project root folder."*
   > Um `bash /home/site/wwwroot/startup.sh` dá
   > `No such file or directory` mesmo com o build inteiro correto.
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
   | `BERTIMBAU_PATH` | `/home/modelos/bertimbau-emi-1.0.0` |
   | `BERTIMBAU_REPO_HF` | `emi-youtube/bertimbau-emi` (o repositório privado da seção 1) |
   | `BERTIMBAU_REVISAO_HF` | `main`, ou o hash do commit no Hub, para fixar |
   | `HF_TOKEN` | o token de **leitura** do repositório — é segredo |
   | `APP_ENV` | `production` |
   | `CORS_ORIGINS` | o domínio da Vercel, ex.: `https://emi-youtube-analytics.vercel.app` |
   | `FRONTEND_URL` | o domínio da Vercel (base dos links de convite e de redefinição de senha) |
   | `EMAIL_PROVEDOR` | `resend` (ou `log` enquanto não houver conta — ver passo B.2) |
   | `RESEND_API_KEY` | a chave da API do Resend — é segredo |
   | `EMAIL_REMETENTE` | ex.: `Emi Analytics <nao-responda@seu-dominio>` (domínio verificado no Resend) |
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

11. Depois do primeiro deploy, abra **Log stream** e confirme, nesta ordem:
    `[startup] diretorio do app: /tmp/...`, `[startup] python:`,
    `[sentilex] ok:` e a migration do Alembic. A partir daí são **duas trilhas
    em paralelo**, e as linhas delas podem se intercalar:
    - **API** (primeiro plano): `Uvicorn running on http://0.0.0.0:...` — sobe
      logo depois da migration, sem esperar o modelo;
    - **runner** (segundo plano): o download do BERTimbau (no primeiro arranque,
      alguns minutos; nos seguintes, só a conferência), `[bertimbau] pasta
      completa e conferida`, `[runner] iniciando`, `bertimbau carregado ...
      versao=1.0.0`, `versao de modelo ativada ... nome=bertimbau-emi` e
      `workers iniciados etapas=coleta,inferencia,topicos classificador=bertimbau-emi 1.0.0`.

    O download fica no runner, e não antes da API, porque ~420 MB podem passar do
    tempo limite de inicialização do App Service: o Azure reiniciaria o contêiner
    e o download recomeçaria em laço. Execuções disparadas enquanto ele baixa só
    esperam na fila.
    Se aparecer `classificador=lexico-sentilex`, o BERTimbau não subiu: o motivo
    está na linha `BERTimbau indisponivel` logo acima (ou em
    `[bertimbau] download falhou`).

    > O primeiro caminho apontar para `/tmp/<uid>` e não para `wwwroot` é o
    > esperado — ver a nota do passo A4.

12. Teste a API: abra `https://<nome>.azurewebsites.net/api/v1/health` — tem de
    responder `{"status":"ok","database":"connected"}`.

### B. Azure — a migration do reaper

Nada a fazer: a migration `0009` roda sozinha no arranque (passo 2 do
`startup.sh`), antes de qualquer processo atender. Se preferir aplicá-la antes
do primeiro deploy, é `alembic upgrade head` apontando para o mesmo banco.

### B.1. Azure — a migration 0011 (empresas) e a ordem segura do deploy

A `0011` (ADR-011 em `docs/BANCO.md`) roda sozinha no arranque, como as outras — o
`startup.sh` faz `alembic upgrade head` ANTES de subir a API. Mergear na `main` já a
aplica em produção no deploy seguinte. A ordem é:

1. **Backup antes.** Supabase → Database → Backups (o plano free guarda o diário),
   ou um `pg_dump` das tabelas `usuarios` e `modelos_analise`.
2. **Ensaio num Postgres descartável**, com os dados copiados se possível:
   `EMI_TESTE_MIGRACAO_URL=... pytest tests/test_migracao_0011.py` (upgrade,
   downgrade e upgrade de novo, com dados).
3. **Merge → deploy.** No arranque do contêiner novo a migração roda e só então a API
   nova sobe.
4. **Conferência:** `EMI_TESTE_POSTGRES_URL=<Supabase> pytest tests/test_rls.py`
   (só lê o catálogo) e um login com uma conta antiga — ela aparece como dona de uma
   empresa com o nome da parte local do e-mail. Ainda não há tela para renomear a
   empresa; se precisar, é um `UPDATE empresas SET nome = ...` pontual.

**O intervalo em que o código ANTIGO convive com o schema NOVO.** Se o App Service
mantiver o contêiner antigo atendendo enquanto o novo arranca, existe uma janela de
segundos com schema 0011 e código anterior. O que acontece nela:

| Operação do código antigo | Efeito |
|---|---|
| login, `/auth/eu`, leitura de modelos/execuções/resultados, painel | funciona (colunas novas são ignoradas; `id_usuario` continua lá) |
| `/auth/refresh` | funciona (`substituido_em` é nula e sem default — testado) |
| workers (coleta, inferência, tópicos) | funcionam (não tocam nas colunas novas) |
| **cadastro** (`POST /auth/registrar`) | **falha com 500**: `usuarios.id_empresa` é NOT NULL |
| **criar modelo** (`POST /modelos-analise`) | **falha com 500**: `modelos_analise.id_empresa` é NOT NULL |

Ou seja: nada corrompe dado, e só as duas escritas acima falham durante a janela.
Faça o deploy em horário sem uso. Se um dia isso não for aceitável, o caminho é
partir em duas migrações (expand/contract): uma cria as colunas nulas com backfill,
outra, num deploy seguinte, as torna NOT NULL.

**Não aplique a 0011 no Supabase fora desse fluxo** (por exemplo, rodando `alembic
upgrade head` da sua máquina) enquanto a produção estiver com o código antigo: a
janela acima deixaria de ser de segundos.

### B.2. E-mail transacional (convites e "esqueci minha senha")

O backend envia dois e-mails: o convite para a empresa e o link de redefinição de
senha. O provedor escolhido é o **Resend** (plano gratuito: 3.000 e-mails/mês, 100
por dia — sobra para o projeto), chamado por HTTP direto, sem SDK.

1. Crie a conta em resend.com e gere uma **API key** com permissão só de envio.
2. **Domínio:** sem domínio verificado, o Resend só entrega para o e-mail da própria
   conta (remetente `onboarding@resend.dev`). Para convidar pessoas de verdade,
   verifique um domínio (Domains → Add, e os registros DNS que ele pedir) e use um
   remetente desse domínio em `EMAIL_REMETENTE`.
3. No App Service: `EMAIL_PROVEDOR=resend`, `RESEND_API_KEY`, `EMAIL_REMETENTE` e
   `FRONTEND_URL` (tabela do passo A6).

**Sem provedor** (`EMAIL_PROVEDOR=log`, o padrão): em desenvolvimento o e-mail inteiro,
com o link, vai para o log do servidor — é assim que se testa o fluxo localmente. Em
`APP_ENV=production` o log só avisa que NÃO enviou, sem o link: link de redefinição em
log de produção seria credencial exposta. O convite continua utilizável sem e-mail,
porque a tela do dono mostra o link uma vez para ser enviado por outro canal.

Uma falha do provedor nunca vira erro para quem pediu: o envio roda depois da
resposta, e o erro vai para o log (`falha ao enviar e-mail provedor=resend`).

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

A terceira linha tem **três causas possíveis**, e elas se distinguem pelas duas
primeiras linhas do log.

**Causa 1 — o Startup Command usa caminho absoluto.** É a mais comum, e o log
NÃO reclama do build: ele mostra `Found build manifest file`, extrai o
`output.tar.zst` e diz `App path is set to '/tmp/<uid>'`. Tudo funcionou — o
app só não está onde o comando procura. Com build automático o conteúdo roda de
`/tmp/<uid>`, e o `wwwroot` guarda apenas o tarball e o manifesto.

**Correção:** Startup Command = `bash startup.sh` (relativo). Ver a nota do
passo A4.

**Causa 2 — os dois fluxos brigando.** Aqui o log reclama do build:
`Could not find build manifest file` e `Could not find virtual environment
directory`. O deploy manda um pacote pronto e as App settings pedem build no
servidor, ou vice-versa. Confira:

| Setting | Valor |
|---|---|
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `1` |
| `ENABLE_ORYX_BUILD` | `true` |
| `WEBSITE_RUN_FROM_PACKAGE` | **não deve existir** |

**Causa 3 — o zip com um nível a mais.** Se o arquivo for montado a partir da
pasta (`zip -r pacote.zip pacote`) em vez de a partir de dentro dela, tudo fica
sob `pacote/` e o `startup.sh` não fica na raiz do app extraído. O workflow monta
o zip de dentro da pasta e **falha** se `startup.sh` não estiver na raiz, então
isto não deve voltar; a nota fica para quem publicar à mão.

O `startup.sh` ajuda a separar as três: ele imprime `[startup] diretorio do app:`
e `[startup] python:` logo no começo e, se faltar dependência, nomeia as App
settings a conferir.

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
