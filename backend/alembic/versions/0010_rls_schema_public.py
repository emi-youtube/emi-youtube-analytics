"""liga Row-Level Security em todas as tabelas do schema public, sem politica

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-30

O Supabase expoe o schema public pela API automatica (PostgREST) a quem tiver a chave
`anon`, que e publica por natureza -- vai embutida em qualquer frontend que use o SDK.
O projeto nunca usa essa API (CLAUDE.md Secao 2: o Supabase e so Postgres gerenciado;
o Angular fala com o FastAPI, e o FastAPI com o banco), mas ela existe mesmo assim. Com
RLS desligado, e com os GRANTs padrao do Supabase ao papel `anon`, qualquer um podia
ler, alterar e apagar qualquer tabela -- inclusive `usuarios.senha_hash`. O Security
Advisor acusou "rls_disabled_in_public".

**ENABLE sem politica nenhuma.** Com RLS ligado e zero politicas, o Postgres nega toda
linha a quem nao for dono da tabela nem tiver BYPASSRLS: o PostgREST (papeis `anon` e
`authenticated`) passa a ver tabela vazia e nao consegue escrever. Criar politica seria
abrir de novo o que se quer fechado.

**Sem FORCE.** FORCE ROW LEVEL SECURITY aplicaria o RLS tambem ao DONO das tabelas, que
e o papel da DATABASE_URL (`postgres`), e o backend passaria a ver zero linhas. O
backend continua funcionando por duas razoes independentes, conferidas no banco antes
de aplicar: `postgres` e dono das 15 tabelas e tem BYPASSRLS. Ver ADR-010 em
docs/BANCO.md.

A lista e explicita, e nao um laco sobre o catalogo: a migration diz exatamente o que
ela muda, e o `downgrade` desfaz exatamente isso. Quem garante que nenhuma tabela
FUTURA escapa e o teste `tests/test_rls.py`, contra Postgres, e a regra no CLAUDE.md.

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As 10 de dominio, as 4 de infraestrutura e a do proprio Alembic.
TABELAS = (
    "usuarios",
    "modelos_analise",
    "execucoes",
    "videos",
    "comentarios",
    "analises_sentimento",
    "versoes_modelo",
    "exemplos_treinamento",
    "temas",
    "comentario_tema",
    "jobs",
    "jobs_dlq",
    "tokens_atualizacao",
    "tentativas_login",
    "alembic_version",
)


def upgrade() -> None:
    for tabela in TABELAS:
        op.execute(f'ALTER TABLE public."{tabela}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for tabela in TABELAS:
        op.execute(f'ALTER TABLE public."{tabela}" DISABLE ROW LEVEL SECURITY')
