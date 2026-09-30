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
