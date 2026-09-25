# CLAUDE.md — Emi YouTube Analytics

Contexto permanente do projeto. Leia antes de qualquer tarefa.

---

## 1. O que é

Plataforma que ajuda **pequenas e médias empresas** a entender como o público reage aos seus vídeos publicitários no YouTube. O sistema coleta comentários de vídeos de campanha, classifica o sentimento de cada um (positivo/negativo/neutro) com um modelo próprio, agrupa temas recorrentes e apresenta tudo num dashboard.

É um **TCC de Ciência da Computação (UNIP)**, 4 integrantes, com documento acadêmico em `docs/`. Decisões técnicas precisam ser defensáveis em banca, não só funcionar.

**Escopo por execução:** 500 a 5.000 comentários. Não otimize para escala além disso.

---

## 2. Stack — decisões travadas

Não sugira trocar. Cada uma tem justificativa registrada no documento acadêmico.

| Camada | Tecnologia | Por quê |
|---|---|---|
| Frontend | **Angular** + SSR (Angular Universal) | decisão da equipe |
| Backend + workers | **Python / FastAPI** | compatibilidade nativa com `transformers` (BERTimbau) |
| Banco | **PostgreSQL** via Supabase (só como Postgres gerenciado) | camada gratuita permanente |
| Fila de jobs | **tabela `jobs` no próprio Postgres** | evita serviço de fila pago |
| Classificação | **BERTimbau** fine-tuned, rodando **local** | sem custo por token, sem enviar dados a terceiros |
| Tópicos | LDA ou clustering de embeddings | insights por execução |
| Treino | Google Colab (GPU T4 gratuita) | offline, sob demanda |
| Hospedagem | Vercel (front) + Azure for Students (back) | créditos acadêmicos |

**Supabase é usado APENAS como Postgres.** Não use Supabase Auth, RLS, Realtime nem o SDK no frontend. O Angular só conversa com o FastAPI; o FastAPI conversa com o banco.

---

## 3. Estrutura do repositório

```
backend/           FastAPI: API REST, autenticação, workers
frontend/          Angular SSR
ml/                pipeline de IA (exportação, rotulagem, treino, avaliação)
preprocessamento/  pacote compartilhado: preparar_texto (layout src/, stdlib pura)
lexico/            pacote compartilhado: SentiLex + soma de polaridade (idem)
```

O documento acadêmico (TC2) e os diagramas ficam fora do repositório.

O `ml/` produz o modelo; o `backend/` o consome. **Não misture:** nada de `ml/` importa de `backend/` e vice-versa — a comunicação é por artefato (arquivo de modelo + `model_card.json`).

**Exceção por desenho, não por quebra de regra:** o que os dois lados precisam executar **de forma idêntica** mora num pacote próprio na raiz, que ambos importam (layout `src/`, stdlib pura, instalado com `pip install -e` nos dois ambientes). São dois:

- **`preprocessamento/`** — `preparar_texto`. Se treino e inferência pré-processassem diferente, o modelo receberia em produção um texto que nunca viu no treino.
- **`lexico/`** — a soma de polaridade sobre o SentiLex. Ela é ao mesmo tempo a linha de base do Capítulo 5 (rodada pelo `ml/`) e a primeira implementação do worker de inferência, enquanto o BERTimbau oficial não existe. Duas cópias divergiriam, e o piso publicado deixaria de descrever o que a PME vê no painel. Nasceu em `ml/lexico/sentilex.py` e mudou de casa quando o worker passou a precisar dela; em `ml/lexico/` ficou o que é experimento.

O critério para criar um terceiro: código que as duas metades têm de executar igual, e cuja divergência seria silenciosa. Não é atalho para compartilhar utilitário.

**Quem vê qual texto:** o pré-processamento existe por limitação do tokenizer do BERTimbau (não tem nenhum emoji no vocabulário). Por isso ele se aplica **só na entrada do BERTimbau** — no treino e no worker de inferência. Avaliadores humanos e a Gemini leem o texto **original**. O banco guarda o original; o texto pré-processado é derivado, nunca canônico.

---

## 4. Modelo de dados (10 tabelas + 2 de fila)

```
USUARIOS(id_usuario PK, nome, email UK, senha_hash, papel CK, criado_em)
MODELOS_ANALISE(id_modelo PK, id_usuario FK, nome, termo_pesquisa, filtros JSONB, criado_em)
EXECUCOES(id_execucao PK, id_modelo FK, status CK, iniciado_em, concluido_em)
VIDEOS(id_video PK, id_execucao FK, youtube_video_id UK, titulo, canal, publicado_em, visualizacoes, curtidas)
COMENTARIOS(id_comentario PK, id_video FK, youtube_comment_id UK, autor_hash, texto, publicado_em)
ANALISES_SENTIMENTO(id_analise PK, id_comentario FK+UK, id_versao_modelo FK, sentimento CK, tema, justificativa, processado_em)
VERSOES_MODELO(id_versao PK, nome_modelo, versao, metricas_avaliacao JSONB, status CK)
EXEMPLOS_TREINAMENTO(id_exemplo PK, id_comentario FK NULL, texto, rotulo_fraco, rotulo_humano, split CK)
TEMAS(id_tema PK, id_execucao FK, rotulo_tema, palavras_chave)
COMENTARIO_TEMA(id_comentario FK, id_tema FK, peso)   -- N:N com atributo
jobs(id_job PK, tipo CK, id_execucao FK, status CK, tentativas, payload JSONB, criado_em)
jobs_dlq(id_job PK, tipo, id_execucao, erro, falhou_em)
tokens_atualizacao(... refresh token revogável — sessão)
tentativas_login(... controle de bloqueio por tentativas — segurança)
```

**Domínio vs. infraestrutura.** As 10 primeiras são **entidades de domínio** e compõem o DER da Seção 4.2.2 do TC2. As quatro últimas (`jobs`, `jobs_dlq`, `tokens_atualizacao`, `tentativas_login`) são **tabelas de infraestrutura**: existem para viabilizar fila, sessão e segurança, não representam conceitos do negócio. Elas não entram no DER — são documentadas na Seção 4.3.2 (Banco de Dados). Ao criar tabela nova, classifique-a antes de decidir onde documentar.

**Valores de CHECK:**
- `papel`: `admin` | `usuario_pme`
- `EXECUCOES.status`: `pendente` | `processando` | `concluida` | `erro`
- `sentimento`: `positivo` | `negativo` | `neutro`
- `VERSOES_MODELO.status`: `ativo` | `arquivado`
- `split`: `treino` | `validacao` | `teste`
- `jobs.tipo`: `coleta` | `inferencia` | `topicos`

Exclusão em cascata: apagar uma EXECUCAO apaga seus VIDEOS → COMENTARIOS → ANALISES.

---

## 5. Arquitetura de execução

```
Angular → API Gateway (JWT) → FastAPI
                                 ↓ publica job (tabela jobs)
              ┌──────────────────┼──────────────────┐
     Worker Coleta        Worker Inferência    Worker Tópicos
     (YouTube API)        (BERTimbau local)    (LDA/clustering)
              └──────────────────┼──────────────────┘
                            PostgreSQL
```

**Formato do modelo em produção:** ponto flutuante de 32 bits (PyTorch ou ONNX). O ONNX int8 foi REPROVADO no ensaio — perdeu 4 pontos de F1 macro e mudou 16% das previsões, contra um limite de 1 ponto. Nova tentativa de quantização só com o modelo definitivo, e sempre com o portão de 1 ponto de F1 e a medição de divergência de previsões.

O `POST /execucoes` **responde 202 Accepted imediatamente** — nunca processa na requisição. Workers consomem a fila por polling com `SELECT ... FOR UPDATE SKIP LOCKED`.

**Uma execução é uma CADEIA de jobs, não um job.** Cada etapa, ao concluir, publica a seguinte **na mesma transação** em que se marca concluída; só a última marca a EXECUCAO como `concluida`. Enquanto houver etapa pendente, a execução fica em `processando` — coletar comentário sem classificar não é resultado nenhum para a PME. A ordem vive num lugar só (`backend/app/workers/pipeline.py`); hoje é `coleta → inferencia`, e o worker de tópicos entra entre os dois. Mesma transação porque uma etapa que se marcasse concluída antes de publicar a próxima poderia morrer no meio: a execução ficaria `processando` para sempre, sem job na fila para ninguém buscar.

**O classificador é uma interface** (`backend/app/inferencia/base.py`), e o worker de inferência é transporte: ele aplica `preparar_texto`, pede um rótulo e grava. A primeira implementação é o **léxico** (SentiLex, o piso do Capítulo 5), porque um piso que classifica é melhor que um painel vazio; o BERTimbau entra como segunda implementação, sem o worker mudar. Toda análise aponta para a linha de `VERSOES_MODELO` da versão que a produziu — é o que dá sentido ao histórico depois da troca.

**Pipeline de treino (offline, fora da aplicação):** comentários → rotulagem fraca via Gemini → validação humana estratificada → fine-tuning BERTimbau no Colab → publica versão → worker de inferência carrega.

---

## 6. Regras críticas — violar quebra o projeto

1. **Nunca commitar segredos.** `.env` está no `.gitignore`. Se precisar de exemplo, crie `.env.example` com valores vazios.
2. **Anonimizar autor de comentário.** Nunca persista nome/ID do autor — só `autor_hash` (SHA-256). Exigência de LGPD, documentada e defendida na banca.
3. **A Gemini NÃO roda em produção.** Ela só aparece em `ml/rotulagem/`, offline. O backend em produção não tem chave de LLM.
   **Exceção prevista como TRABALHO FUTURO, não implementar:** a análise da campanha sob demanda (Seção 11, fase 4).
4. **Nunca chame `search.list` da YouTube API** — custa 100 unidades de cota contra 1 de `commentThreads.list`. Os vídeos são curados manualmente; use os IDs direto.
5. **Ordem dos rótulos vem do `model_card.json`**, nunca hardcoded. O `ml/` exporta `{id2label, max_length, versao, versao_preprocessamento}` junto dos pesos; o backend lê de lá. Hardcodar causa bug silencioso (prevê "negativo", grava "neutro"). Se a `versao_preprocessamento` do card divergir da instalada, o worker de inferência deve recusar o modelo.
6. **Conjunto de teste é só humano.** Nunca avalie o modelo contra rótulos gerados pela Gemini — a comparação vira circular e inválida. `exemplos_treinamento.split` nasce NULO e só é atribuído depois da rotulagem fraca: a amostra humana é sorteada estratificada pelo rótulo fraco (que os avaliadores não veem) e vira `teste`; o restante vai 85/15 para treino e validação.
7. **Tabela de infraestrutura não pode crescer sem limite.** `tentativas_login` e similares precisam de limpeza (apagar registros antigos na própria escrita). O free tier do Supabase tem cota de armazenamento.
8. **`class_weight='balanced'` no treino.** O corpus da Sprint 1 (2.534 comentários, rótulo fraco) é 42,6% positivo / 30,1% neutro / 27,2% negativo — mais negativo que a suposição inicial do planejamento, efeito da curadoria com campanhas de recepção crítica. A métrica que importa é **F1 macro**, não acurácia.

---

## 7. Convenções

- **Nomes de tabelas/colunas em português**, batendo com o documento acadêmico (a banca compara).
- **Código, variáveis e funções em inglês**; comentários e docstrings em português.
- Python: type hints sempre, `ruff` para lint, `async` no FastAPI.
- Rotas versionadas: `/api/v1/...`
- Toda linha de log inclui o `id_execucao` quando houver — sem isso é impossível depurar execuções concorrentes.
- Migrations versionadas (Alembic), nunca alterar schema direto no painel do Supabase.
- **Git — antes de criar qualquer branch:** `git fetch origin`, `git checkout main`, `git pull`. Nunca confie no `main` local sem atualizar; ele fica velho rápido e a branch nasce sem o que já foi mergeado.
- **Todo PR tem base na `main`.** Se parecer que o PR precisa de outra base, pare e pergunte antes de abrir. Já aconteceu três vezes: o `main` local desatualizado parecia não ter o que o PR precisava (o PR #8 foi aberto contra `sprint1/lexico-e-avaliacao` porque `ml/treino/` parecia não existir na `main`, quando já estava lá desde o PR #7).

---

## 8. Estado atual (setembro/2026)

**Sprint 0 — concluída.** Contas criadas: GitHub org, Supabase (região sa-east-1), Azure for Students, Vercel, conta Google do projeto, chaves Gemini e YouTube, Colab com GPU confirmada.

**Em andamento agora, em paralelo:**

- **Sprint 1 (dupla ML):** curadoria manual de 15–20 vídeos publicitários (em andamento, não bloqueia código) → script de coleta → rotulagem fraca → mini-amostra → Kappa → fine-tuning piloto → **gate de decisão**.
- **Sprint 3 (dupla Infra):** schema das 10 tabelas → auth JWT → CRUD de modelo de análise → tabela `jobs` + `POST /execucoes` → worker de coleta → **worker de inferência** (interface do classificador + implementação léxica; o BERTimbau troca a implementação). Falta o worker de tópicos e os endpoints de resultado.

Backlog completo no Trello (board "Emi YouTube Analytics", uma lista por sprint).

---

## 9. Graphify

O projeto usa **Graphify** para dar contexto estrutural do código. **Antes de sair lendo arquivos ou fazendo grep, consulte `graphify-out/GRAPH_REPORT.md`** — ele mapeia módulos, dependências e pontos de entrada, e economiza contexto.

O repositório já tem backend (API, workers, migrations), frontend (Angular), `ml/` e `preprocessamento/`. O grafo é útil agora.

**Quando regenerar (`/graphify .`):**
- ao fim de cada sprint;
- depois de merge de PR que crie módulo novo ou mude a estrutura de pastas;
- se o `GRAPH_REPORT.md` citar arquivo que não existe mais.

Se o relatório estiver desatualizado em relação ao que você encontrar no código, **confie no código** e sinalize que é hora de regenerar. A pasta `graphify-out/` é regenerável e está no `.gitignore`.

## 10. O que NÃO fazer

- Não implemente autenticação via Supabase Auth (o documento especifica JWT próprio — tem valor acadêmico).
- Não otimize para escala além de 5.000 comentários por execução.
- Não adicione Redis, Celery, RabbitMQ, Docker Compose com 6 serviços. A fila é uma tabela. Complexidade extra não cabe no prazo nem no crédito do Azure.
- Não processe coleta ou inferência dentro de uma requisição HTTP.
- Não crie o `TESTE.PY` da raiz como padrão — código solto na raiz não entra no repositório final.
- Não "limpe" os `chr(0xFE0F)` de `preprocessamento/` de volta para literais: são caracteres invisíveis, e o `ruff format` reescreve o escape `"\ufe0f"` para o literal na primeira formatação.
- Não expanda gíria no pré-processamento ("q" → "que"): é normalização semântica que os avaliadores humanos não fazem. Normalização tipográfica (`…` → `...`) pode.

---

## 11. Insights e campanhas

Decisões da equipe (24/09). **Tudo nesta seção é evolução PLANEJADA e CONDICIONADA AO PRAZO.** Nada daqui tem prioridade sobre o caminho crítico: gabarito → Kappa → treino → avaliação (Cap. 5) → workers de inferência e de tópicos. Sem esses workers não existe dado para gerar insight.

### Fluxo do produto

1. O usuário cria uma **campanha** — na interface; no banco continua sendo `MODELOS_ANALISE` (a banca compara com o documento).
2. Adiciona vídeos, cada um com **papel** (`proprio` ou `concorrente`) e **rótulo livre** opcional (ex.: "versão A").
3. Executa a análise como hoje: coleta, classificação, tópicos.
4. O painel mostra a comparação por regras e comentários representativos por tema.
5. Sob demanda, o usuário pede a **análise da campanha** em texto corrido, gerada por IA.

### Fases

- **Fase 3 — papéis, comparação por regras e comentários representativos.** Prioridade alta dentro da evolução.
- **Fase 4 — análise da campanha pela IA generativa. TRABALHO FUTURO (decidido em 25/09). Não implementar.** O UC06 é atendido pelo relatório exportável com indicadores e insights por regras (página própria para impressão).

### Três camadas de insight

1. **Regras sobre os resultados.** Cada insight é um FATO ESTRUTURADO (tipo da regra, valores, amostra de cada valor, origem), e o texto é gerado a partir dele. Nunca escreva insight como string solta.
2. **Comentários representativos por tema,** escolhidos LOCALMENTE: o comentário mais central de cada tema na representação do próprio BERTimbau. É extrativo — mostra um comentário real —, sem serviço externo e sem risco de invenção.
3. **Síntese em texto corrido pela Gemini** (fase 4).

### Regras de método

- Amostra mínima por afirmação; abaixo dela, o insight não é emitido.
- Variação entre execuções só vira insight acima da margem de incerteza das proporções.
- Temas NÃO casam por rótulo entre execuções (a modelagem de tópicos roda por execução). Casar por sobreposição de palavras-chave. Dentro de uma mesma execução, vídeos próprios e de concorrentes compartilham os temas — a comparação entre eles é direta.
- O insight herda o erro do classificador; o texto não afirma além dos números.

### Camada da IA generativa (fase 4)

- Disparada pelo usuário, processada como job na fila existente — nunca dentro da requisição.
- Recebe SÓ fatos agregados: percentuais, nomes de temas, palavras-chave. NUNCA texto de comentário. Os comentários representativos aparecem AO LADO do texto, escolhidos localmente.
- Todo número no texto gerado precisa existir nos fatos; senão, o texto é descartado e vale o texto por regra.
- Indisponibilidade ou erro → texto por regra, sem erro visível.
- Resultado PERSISTIDO com modelo, data, versão do prompt e fatos usados: não paga de novo a cada visita e preserva o registro se o modelo for aposentado.
- Marcado na interface como gerado por IA.
- Corresponde ao UC06 "Gerar relatório estratégico", que existe no diagrama e nunca foi implementado.

### Mudanças de modelo previstas (propostas de nome)

- `VIDEOS_MONITORADOS` (id_modelo FK, youtube_video_id, papel CK, rotulo): os vídeos que a campanha acompanha, com o papel de cada um. Substitui a lista de IDs guardada hoje em `filtros.videos`; a regra de "ao menos um vídeo" do UC02 migra para cá. Não confundir com `VIDEOS`, que é o retrato de cada coleta.
- `SINTESES` (id_modelo FK, fatos JSONB, texto, gerador, versao_prompt, criado_em): as análises geradas.
- `jobs.tipo` ganha um novo valor para a síntese.
- Ao implementar: atualizar DER, casos de uso (UC02 vira "Criar campanha"; UC06 especificado) e o argumento de LGPD do TC2 ("nenhum texto de comentário sai da infraestrutura em produção").
