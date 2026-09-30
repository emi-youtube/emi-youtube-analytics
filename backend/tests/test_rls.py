"""Toda tabela do schema public tem Row-Level Security ligado (ADR-010, docs/BANCO.md).

Sem RLS, a API automática do Supabase (PostgREST) lê, altera e apaga a tabela para
quem tiver a chave `anon`, que é pública. A migration 0010 fechou as tabelas que
existiam; este teste é o que impede uma tabela NOVA de nascer aberta.

**Só roda contra Postgres.** O SQLite dos outros testes não tem RLS, e o `conftest`
aponta a DATABASE_URL para um host inexistente de propósito. Este teste usa uma
variável própria e é pulado sem ela:

    EMI_TESTE_POSTGRES_URL=postgresql+asyncpg://... pytest tests/test_rls.py

Ele só lê o catálogo (`pg_class`); não escreve nada, então pode apontar para o
Supabase depois de `alembic upgrade head`.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

URL_POSTGRES = os.environ.get("EMI_TESTE_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not URL_POSTGRES, reason="so contra Postgres: defina EMI_TESTE_POSTGRES_URL"
)

TABELAS_DO_PUBLIC = text(
    """
    select c.relname, c.relrowsecurity, c.relforcerowsecurity
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'p')
    order by c.relname
    """
)


@pytest.fixture
async def tabelas():
    engine = create_async_engine(URL_POSTGRES)
    try:
        async with engine.connect() as conexao:
            yield (await conexao.execute(TABELAS_DO_PUBLIC)).all()
    finally:
        await engine.dispose()


async def test_toda_tabela_do_public_tem_rls_ligado(tabelas):
    # Um banco vazio passaria no teste sem provar nada.
    assert any(nome == "usuarios" for nome, _, _ in tabelas), "rode alembic upgrade head antes"

    sem_rls = [nome for nome, rls, _ in tabelas if not rls]

    assert sem_rls == [], (
        f"tabelas do public sem RLS: {sem_rls}. Toda tabela nova precisa de "
        "`op.execute('ALTER TABLE public.\"<tabela>\" ENABLE ROW LEVEL SECURITY')` "
        "na migration que a cria (CLAUDE.md Secao 6, ADR-010)."
    )


async def test_nenhuma_tabela_usa_force_rls(tabelas):
    """FORCE aplicaria o RLS também ao dono, que é o papel do backend: ele veria zero linhas."""
    com_force = [nome for nome, _, force in tabelas if force]

    assert com_force == [], f"FORCE ROW LEVEL SECURITY em {com_force}: o backend perde acesso"
