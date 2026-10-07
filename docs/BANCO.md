# Banco de dados — decisões registradas

Decisões sobre o PostgreSQL (Supabase usado só como Postgres gerenciado, CLAUDE.md
Seção 2) que precisam de justificativa além do código das migrações.

---

## ADR-010 — Row-Level Security ligado em todo o schema `public`, sem política

**Status:** aceita e aplicada em 30/09/2026 (migração `0010`).

### Contexto

O Security Advisor do Supabase acusou **`rls_disabled_in_public`** (crítico). Todo
projeto Supabase expõe o schema `public` por uma API REST automática (PostgREST), e
essa API atende quem apresentar a chave `anon`. A chave é pública por natureza: foi
feita para ir embutida em frontend.

O projeto **nunca usa** essa API. O Angular fala só com o FastAPI, e o FastAPI fala com
o banco pela `DATABASE_URL` (CLAUDE.md Seção 2). Mas a API existe mesmo sem uso, e o
Supabase concede ao papel `anon` SELECT, INSERT, UPDATE, DELETE e TRUNCATE nas tabelas
do `public`. Medido antes da correção, com `SET ROLE anon`, que é o que o PostgREST
faz: `anon` via as mesmas linhas que o backend, inclusive as 5 de `usuarios` (com
`senha_hash`) e as 8 de `tokens_atualizacao`, e podia alterá-las e apagá-las.

### Decisão

A migração `0010` executa `ENABLE ROW LEVEL SECURITY` nas 15 tabelas do `public`: as
10 de domínio, as 4 de infraestrutura e a `alembic_version`. **Nenhuma política é
criada, e FORCE não é usado.**

- **Sem política:** com RLS ligado e nenhuma política, o Postgres nega toda linha a
  quem não é dono da tabela nem tem BYPASSRLS. `anon` e `authenticated` passam a ver as
  tabelas vazias, e as escritas deles não afetam linha nenhuma ou são recusadas. Criar
  política seria reabrir o acesso que se quer fechado.
- **Sem FORCE:** `FORCE ROW LEVEL SECURITY` aplicaria o RLS também ao **dono** das
  tabelas, que é o papel do backend, e o backend passaria a ver zero linhas.

### Por que o backend não é afetado

Conferido no catálogo **antes** de aplicar. O papel da `DATABASE_URL` é `postgres`, e
ele passa por duas condições independentes, cada uma suficiente por si:

| Condição | Valor medido |
|---|---|
| Dono das tabelas (`pg_class.relowner`) | `postgres` nas 15 |
| `rolbypassrls` do papel | `true` |
| `rolsuper` do papel | `false` (no Supabase, `postgres` não é superusuário) |

O RLS não se aplica ao dono de uma tabela sem FORCE, e não se aplica a papel com
BYPASSRLS. Se uma das duas mudar, a outra ainda segura. Se as duas mudarem, o sintoma
não é erro de permissão: é o backend passando a ver **tabelas vazias**.

### Validação (30/09/2026, depois de aplicar)

- `SET ROLE anon` e `SET ROLE authenticated`: contagem 0 em `usuarios`,
  `tokens_atualizacao`, `comentarios`, `execucoes` e `alembic_version`. Antes eram as
  mesmas contagens do backend.
- Escrita como `anon`: `UPDATE usuarios` e `DELETE FROM execucoes` afetaram 0 linhas,
  e `INSERT INTO jobs_dlq` foi recusado com "new row violates row-level security
  policy".
- Backend, com o mesmo papel de sempre: `/api/v1/health` respondeu `database:
  connected`. Um login com e-mail inexistente respondeu 401 e gravou a linha em
  `tentativas_login`, ou seja, leu `usuarios` e escreveu normalmente.
- `backend/tests/test_rls.py` falhou antes da migração, listando as 15 tabelas, e passa
  depois dela.

### Consequências

- **Tabela nova nasce aberta** se a migração que a cria não ligar o RLS. O Supabase
  concede os GRANTs a `anon` automaticamente para qualquer tabela nova no `public`.
  Duas proteções contra isso:
  1. regra 9 do CLAUDE.md (Seção 6): a migração que cria a tabela liga o RLS;
  2. `backend/tests/test_rls.py`, que lê o `pg_class` e falha se alguma tabela do
     `public` estiver sem RLS, ou se alguma usar FORCE. Roda só contra Postgres, porque
     o SQLite dos demais testes não tem RLS:
     `EMI_TESTE_POSTGRES_URL=postgresql+asyncpg://... pytest tests/test_rls.py`.
     Só lê o catálogo, então pode apontar para o Supabase.
- **TRUNCATE não passa pelo RLS.** Ele continua concedido a `anon`, mas o PostgREST não
  expõe TRUNCATE, então não há caminho até ele pela chave pública. Revogar os GRANTs de
  `anon` e `authenticated` seria uma segunda camada. Ficou de fora desta decisão porque
  o Supabase recoloca os GRANTs em tabela nova; a camada que vale para toda tabela,
  inclusive as futuras, é o RLS.
- **Supabase Auth, Realtime e o SDK continuam fora** (CLAUDE.md Seção 10). Sem
  política, nenhum deles enxergaria os dados, e isso é o desejado.

---

## ADR-011 — Isolamento por EMPRESA, não por usuário

**Status:** aceita (migração `0011`, branch `sprint4/empresa-e-autenticacao`). Ainda
não aplicada em produção.

### Contexto

Até a `0010` o dono de tudo era o USUÁRIO: `MODELOS_ANALISE.id_usuario` e os
`get_owned` filtravam por `usuario.id_usuario`. Uma PME, porém, é uma equipe: o
analista que cria a campanha e a gerente que lê o painel precisam ver os mesmos
modelos, execuções e resultados. Com isolamento por usuário a única saída seria
compartilhar a senha — o oposto do que a Seção de segurança do TC2 defende.

### Decisão

1. **A unidade de isolamento passa a ser a empresa.** Tabela `EMPRESAS`;
   `USUARIOS.id_empresa` (obrigatório) e `USUARIOS.papel_empresa` (`dono` | `membro`);
   `MODELOS_ANALISE.id_empresa` (obrigatório). `MODELOS_ANALISE.id_usuario` continua,
   agora como **autor**.
2. **O filtro de posse mora num lugar só:** `backend/app/services/escopo.py`
   (`da_empresa(usuario)`). Todo `get_owned`, listagem, resultado e o painel chegam a
   `MODELOS_ANALISE` e aplicam esse filtro. Recurso de outra empresa continua
   respondendo **404**, nunca 403.
3. **Entrada por convite.** O dono gera um convite (token aleatório de 32 bytes, só o
   SHA-256 no banco, 7 dias, uso único, preso a um e-mail). Teto de
   `EMPRESA_MAX_MEMBROS` (10) membros por empresa, contando convites pendentes.
4. **Papel global `admin` independe da empresa.** Admin também pertence a uma
   empresa e só vê os dados dela; `papel` (global) e `papel_empresa` são eixos
   diferentes.
5. **Remover um membro apaga a conta.** Não existe usuário sem empresa, então sair da
   empresa é sair do sistema. Os dados são da empresa e ficam: a autoria dos modelos
   do removido passa para o dono que removeu (`id_usuario` é obrigatório). Refresh
   tokens, convites criados por ele e links de redefinição saem em cascata. O dono não
   remove a si mesmo, e a empresa nunca fica sem dono.

### Tabelas novas e classificação

| Tabela | Classe | Onde documentar |
|---|---|---|
| `EMPRESAS` | domínio | DER (Seção 4.2.2) |
| `CONVITES` | domínio (a empresa convida pessoas) | DER (Seção 4.2.2) |
| `TOKENS_REDEFINICAO_SENHA` | infraestrutura (segurança) | Seção 4.3.2 |

Dicionário de dados (o que muda no TC2):

```
EMPRESAS(id_empresa PK, nome varchar(120) NN, criada_em timestamptz NN default now())
USUARIOS(+ id_empresa FK->EMPRESAS NN, + papel_empresa varchar(10) NN CK in (dono, membro))
MODELOS_ANALISE(+ id_empresa FK->EMPRESAS NN)            -- id_usuario passa a ser o autor
CONVITES(id_convite PK, id_empresa FK->EMPRESAS NN ON DELETE CASCADE,
         email varchar(255) NN, token_hash varchar(64) NN UK,
         papel_empresa varchar(10) NN CK in (dono, membro),
         criado_por FK->USUARIOS NN ON DELETE CASCADE,
         expira_em timestamptz NN, usado_em timestamptz NULL, criado_em timestamptz NN)
TOKENS_REDEFINICAO_SENHA(id_token PK, id_usuario FK->USUARIOS NN ON DELETE CASCADE,
         token_hash varchar(64) NN UK, expira_em timestamptz NN,
         usado_em timestamptz NULL, criado_em timestamptz NN)
TOKENS_ATUALIZACAO(+ substituido_em timestamptz NULL)    -- rotação do refresh
```

Relacionamentos para o DER: EMPRESAS 1:N USUARIOS; EMPRESAS 1:N MODELOS_ANALISE;
EMPRESAS 1:N CONVITES; USUARIOS 1:N CONVITES (criado_por).

**Índices:** `ix_usuarios_id_empresa`, `ix_modelos_analise_id_empresa` (o filtro de
posse de toda consulta), `ix_convites_id_empresa`,
`ix_tokens_redefinicao_senha_id_usuario` e `ix_tokens_atualizacao_id_usuario` (revogar
"todos os tokens do usuário" na troca de senha e na detecção de reuso). Os `token_hash`
têm índice pela própria UNIQUE.

**RLS:** ligado nas três tabelas novas na própria `0011`, sem política e sem FORCE
(ADR-010). `test_rls.py` passou a conferir as três pelo nome.

### Backfill

Na mesma migração: cada usuário existente ganha uma empresa própria (nome = parte
local do e-mail, `criada_em` = cadastro do usuário), vira `dono`, e os modelos dele
recebem o `id_empresa`. Ninguém passa a ver nada que não via: cada empresa nasce com
exatamente um membro. As colunas nascem nulas, são preenchidas e só então viram NOT
NULL. Upgrade, downgrade e novo upgrade testados com dados contra Postgres em
`backend/tests/test_migracao_0011.py` (banco descartável; nunca o Supabase).

### Retenção (regra 7)

- `TOKENS_ATUALIZACAO`: com rotação, cada refresh deixa uma linha. As vencidas saem a
  cada emissão de token do usuário; as substituídas ainda dentro do prazo ficam, porque
  são elas que denunciam o reuso. Teto prático: refreshes de 7 dias por usuário.
- `TOKENS_REDEFINICAO_SENHA`: no máximo 3 por conta por hora; as mais velhas que 1 h
  saem a cada novo pedido.
- `CONVITES`: os vencidos (usados ou não) da empresa saem a cada convite novo; um
  pendente por e-mail (reconvidar substitui).

### Autenticação que acompanhou a mudança

- **Rotação do refresh:** cada `/auth/refresh` devolve um par novo e carimba
  `substituido_em` no antigo. Um refresh já substituído que reaparece é cópia: todos os
  refresh tokens do usuário são revogados, a resposta é 401 e o evento sai no log como
  `evento=refresh_token_reuso`. A marcação é um `UPDATE ... WHERE substituido_em IS
  NULL`, então duas chamadas simultâneas com o mesmo token não ganham dois sucessores.
- **Troca de senha** (logado) e **redefinição** (link de 30 min, uso único) revogam
  todos os refresh tokens; a redefinição também zera o bloqueio por tentativas. A
  senha atual errada na troca conta no mesmo contador do login.
- **"Esqueci minha senha"** responde sempre 202 com o mesmo corpo; o e-mail sai em
  segundo plano para o tempo de resposta não depender de a conta existir. Limite de 5
  pedidos por IP a cada 15 min (em memória do processo; a API roda com 1 worker) e de
  3 links por conta por hora (silencioso).

### Consequências e limites conhecidos

- **Access token já emitido vale até expirar (15 min)** depois de uma troca de senha
  em OUTRA sessão: JWT não é revogável sem consulta. Remoção de membro não tem essa
  janela, porque `get_usuario_atual` relê o usuário a cada requisição.
- **Duas abas renovando ao mesmo tempo** podem ser lidas como reuso e derrubar a
  sessão. Dentro de uma aba o frontend serializa o refresh (`shareReplay`); entre
  abas, não. O custo é entrar de novo com a senha.
- **Verificação de e-mail no cadastro: melhoria futura, não implementada.** Quem
  entra por convite já provou a posse do e-mail (o link chegou nele e o cadastro
  exige o mesmo endereço). Quem cria empresa nova ainda não prova; isso só pesa se um
  e-mail alheio for cadastrado antes do dono real — que então recupera a conta pelo
  "esqueci minha senha".
- **Downgrade** volta ao isolamento por usuário: quem entrou por convite mantém a
  conta, mas deixa de ver os modelos dos colegas.

---

## ADR-012 — Aceite dos termos e direitos do titular sobre a própria conta (LGPD)

**Status:** aceita (migração `0012`, branch `sprint4/termos-e-lgpd`). Ainda não
aplicada em produção.

### Contexto

O sistema guarda dados pessoais de duas origens: de quem tem conta (nome, e-mail,
empresa, papel) e dos autores dos comentários coletados do YouTube. A LGPD pede base
legal para cada tratamento, registro do aceite dos termos, e atendimento dos direitos
do titular — em especial acesso (art. 18, II) e eliminação (art. 18, VI). Até a `0011`
não havia registro de aceite nem caminho para a pessoa exportar ou apagar os próprios
dados.

### Decisão

1. **Aceite registrado por versão.** Tabela `ACEITES_TERMOS`, uma linha por (usuário,
   versão aceita). A versão vigente é a constante `VERSAO_TERMOS` em
   `backend/app/core/config.py`, que muda junto com o arquivo
   `frontend/src/assets/legal/termos-v<versão>.md`. Trocar a constante deixa todo
   mundo pendente, sem tocar no banco.
2. **Cadastro exige o aceite** (`aceite_termos: true`, 422 sem ele), nos dois caminhos
   (criar empresa e entrar por convite), e grava o aceite **no mesmo commit** da conta:
   não existe conta nova sem aceite.
3. **Sem backfill.** Aceite é ato da pessoa, não da migração. Contas anteriores à
   `0012` aparecem com `termos_pendentes: true` em `GET /auth/eu`, e o frontend abre um
   modal bloqueante; recusar encerra a sessão. A API não bloqueia as outras rotas por
   pendência — quem barra é a interface; o registro é o que serve de prova.
4. **Sem IP no aceite.** Considerado e retirado do escopo: atrás da Vercel e do proxy
   do Azure, o IP que chega à API não é confiável como evidência (a leitura do IP em
   `ip_do_cliente` está num card separado). O aceite registra quem, qual versão e
   quando.
5. **Acesso:** `GET /conta/meus-dados` devolve cadastro, empresa, papéis, aceites e a
   lista dos modelos que a pessoa CRIOU (nome e data). A resposta é uma lista fechada
   de campos: `senha_hash`, tokens e dados de colegas não aparecem nem por engano.
6. **Eliminação:** `DELETE /conta`, com a senha no corpo e sob o mesmo bloqueio por
   tentativas do login (não vira oráculo de senha). O que sai depende do papel, porque
   os dados de análise são da EMPRESA (ADR-011):
   - **membro:** sai a conta; os modelos que criou passam a um dono da empresa (mesma
     regra de remover membro) e as execuções ficam com a empresa;
   - **dono único:** sai a empresa inteira — modelos, execuções, jobs, DLQ, vídeos,
     comentários, análises, temas, convites —, além dos tokens e aceites;
   - **dono com outros membros:** recusado (409). Transferir a posse ainda não existe;
     *atualizado pelo ADR-013: com outro dono presente, o dono pode sair;*
   - **execução em andamento** (dono único): recusado (409), porque o worker gravaria
     num vídeo que acabou de sair e a etapa terminaria em erro de chave estrangeira.

   Tudo numa transação; os refresh tokens, links de redefinição e as tentativas de
   login do e-mail saem junto. O evento vai ao log como `evento=conta_excluida` com
   `id_usuario`, `id_empresa` e `apagou_empresa`, nunca com o e-mail.

### Exclusão em cascata: o que o banco faz e o que o código faz

`EXECUCOES`, `JOBS`, `JOBS_DLQ` e `TEMAS` **não** têm `ON DELETE CASCADE` — apagar um
modelo executado é barrado de propósito (CLAUDE.md Seção 4). Por isso a exclusão da
empresa apaga explicitamente, de baixo para cima:

```
jobs_dlq -> jobs -> temas -> videos -> execucoes -> modelos_analise -> convites
         -> tokens / aceites / tentativas_login -> usuarios -> empresas
```

`VIDEOS` leva `COMENTARIOS` por cascata do banco, que leva `ANALISES_SENTIMENTO` e
`COMENTARIO_TEMA`. A ordem está em `backend/app/services/conta.py` e foi testada contra
Postgres (`tests/test_migracao_0012.py`) com duas empresas: depois de apagar uma, o
banco volta exatamente à fotografia da outra.

**`EXEMPLOS_TREINAMENTO` fica.** A FK para `COMENTARIOS` é `SET NULL`: o exemplo
perde a referência e mantém o texto. O corpus de treino é do projeto, não da empresa,
e o texto é de um autor do YouTube, não do titular que excluiu a conta. A decisão está
declarada aos usuários na seção 6 dos termos ("Corpus de pesquisa"): o texto permanece
depois da exclusão da conta ou da empresa e não é publicado com identificação do autor.

### Bases legais por dado

Transcritas da seção 4 dos termos vigentes (`termos-v1.1.md`), que é a fonte oficial: se um dia
divergirem, vale o texto dos termos e esta tabela é corrigida. A coluna "No sistema"
diz onde cada dado mora.

| Dado | Base legal (LGPD, art. 7º), como nos termos | No sistema | Retenção |
|---|---|---|---|
| e-mail, senha e nome da empresa | execução do serviço solicitado (V) | `USUARIOS`, `EMPRESAS`; senha só como hash bcrypt | enquanto a conta existir |
| termos aceitos (versão e data) | cumprimento de obrigação / legítimo interesse | `ACEITES_TERMOS` | sai com a conta |
| comentários públicos do YouTube | legítimo interesse acadêmico; dado tornado público (§4º) | `COMENTARIOS`, autor **pseudonimizado** (SHA-256) | até 3 meses após a execução — ver pendência abaixo |
| registros técnicos (logs, tentativas de login) | legítimo interesse (IX) | `TENTATIVAS_LOGIN` (hash do e-mail) | 24 h (regra 7) |
| respostas da validação humana | consentimento (I), pelo TCLE | fora deste banco | documento próprio |

O autor do comentário é **pseudonimizado, não anonimizado**: o mesmo autor gera sempre
o mesmo hash, e quem tem o identificador original consegue recalculá-lo. Dado
pseudonimizado (art. 13, §4º) continua sendo dado pessoal — só o anonimizado sai do
alcance da lei (art. 12). O texto dos termos diz isso ("pseudonimização, não
anonimização completa").

### Pendência conhecida: expurgo automático das execuções

A seção 6 dos termos prevê excluir comentários e resultados até **3 meses** após a
execução. **O expurgo automático AINDA NÃO existe**: hoje a execução fica até a empresa ser excluída,
e os termos dizem isso ("até lá, a exclusão é feita sob pedido"). Quando for feito, o
caminho natural é a mesma ordem de `_apagar_empresa`, aplicada às execuções vencidas, e
uma linha nova neste ADR.

### Tabela nova e classificação

| Tabela | Classe | Onde documentar |
|---|---|---|
| `ACEITES_TERMOS` | infraestrutura (conformidade LGPD) | Seção 4.3.2, fora do DER |

Dicionário de dados:

```
ACEITES_TERMOS(id_aceite PK,
               id_usuario FK->USUARIOS NN ON DELETE CASCADE,
               versao_termos varchar(20) NN,
               aceito_em timestamptz NN default now(),
               UK uq_aceites_termos_usuario_versao (id_usuario, versao_termos))
```

A UNIQUE torna o aceite idempotente (dois cliques simultâneos não duplicam) e serve de
índice por `id_usuario` (coluna da esquerda), a única busca feita na tabela — por isso
não há índice separado.

**Retenção (regra 7):** no máximo uma linha por usuário por versão dos termos, e sai
com o usuário. Não precisa de poda.

**RLS:** ligado na própria `0012`, sem política e sem FORCE (ADR-010). `test_rls.py`
confere a tabela pelo nome.

---

## ADR-013 — Privilégios do dono: quem altera o quê, promover/rebaixar e saída do dono

**Status:** aceita (sem migração; branch `sprint4/privilegios-do-dono`).

### Contexto

O ADR-011 tornou a EMPRESA dona dos dados, mas deixou todo membro com o mesmo poder
sobre os modelos: qualquer um editava ou apagava o modelo de um colega. O dono, por
outro lado, não tinha como dividir a posse — e o ADR-012 recusava a saída de um dono
com membros sem oferecer saída.

### Decisão

1. **Editar e apagar modelo: o autor ou um dono.** `modelos_analise.id_usuario` (o
   autor) passa a valer para permissão. A ordem das checagens é fixa: primeiro o
   escopo da empresa (`escopo.da_empresa`, **404** para outra empresa), depois o papel
   (`permissao.pode_alterar_modelo`, **403** dentro da empresa). O 409 de modelo com
   execuções continua. Ler, executar e criar seguem livres para todo membro.
2. **A lista de modelos diz quem criou** (`autor_nome`) e se quem pergunta pode
   alterar (`pode_alterar`). Só o nome do autor: o e-mail do colega não sai por aí.
3. **Promover e rebaixar:** `PATCH /empresa/membros/{id}` com `papel_empresa`, só para
   dono. Alvo de outra empresa: 404. Rebaixar exige que sobre outro dono (vale para
   rebaixar a si mesmo). Teto de **3 donos** (`EMPRESA_MAX_DONOS`), contando os
   convites de dono pendentes — senão convites furariam o teto; o aceite de convite
   confere de novo. Log: `evento=papel_alterado id_empresa alvo de para por`.
4. **Mudança de papel vale na hora.** Não há sessão a revogar: `get_usuario_atual`
   relê o usuário a cada requisição, então o rebaixado perde as rotas de dono já na
   chamada seguinte, com o mesmo access token (testado).
5. **Saída do dono (`DELETE /conta`):**
   - sozinho na empresa → apaga a empresa (ADR-012);
   - único dono com outros membros → **409**, "Promova outro membro a dono antes de
     sair";
   - com outro dono → sai; os modelos que criou vão ao **dono mais antigo** que fica
     (`criado_em`, depois `id_usuario`), e a empresa continua;
   - membro → como antes (os modelos vão ao dono mais antigo).
   Os convites que o dono que sai criou caem em cascata (`convites.criado_por`).

### Quem pode o quê

| Ação | Membro | Dono | Admin (papel global) |
|---|---|---|---|
| ver modelos, execuções, resultados, painel, membros | ✔ | ✔ | — reservado |
| criar modelo, executar análise | ✔ | ✔ | — reservado |
| editar / apagar modelo | só os que criou | todos da empresa | — reservado |
| convidar, revogar convite, remover membro | ✘ (403) | ✔ | — reservado |
| promover / rebaixar | ✘ (403) | ✔ (sobra ≥ 1 dono; teto de 3) | — reservado |
| baixar os próprios dados, excluir a conta | ✔ | ✔ (regras de saída acima) | — reservado |

"Admin — reservado": o papel global `admin` existe (`USUARIOS.papel`) e só serve à
rota de teste de `requer_admin`. Ele não dá poder dentro de uma empresa e não aparece
em tela; o admin é dono ou membro da própria empresa como qualquer um.

### Consequências e limites

- **Sem migração.** O autor do modelo já existia (`id_usuario`); o nome dele vem por
  relacionamento só de leitura no ORM.
- **`GET /empresa/membros` mostra o e-mail de todos a qualquer membro** (ADR-011).
  Não muda aqui; se a regra "e-mail de colega só para o dono" valer também para a
  lista de membros, é uma mudança à parte.
- O diagrama de casos de uso fica fora do repositório: o ator "Dono da empresa"
  (especialização de "Usuário") precisa ser acrescentado lá, com os casos "Gerenciar
  membros" e "Alterar papel".
