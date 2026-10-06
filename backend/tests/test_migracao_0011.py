"""Migração 0011 com DADOS: backfill de empresas, upgrade e downgrade, contra Postgres.

**DESTRUTIVO: só contra um banco descartável.** O teste desce o schema até a 0010,
grava linhas, sobe, desce de novo e sobe até o fim. Por isso usa uma variável
própria, diferente da do `test_rls.py` (que só lê o catálogo e pode apontar para o
Supabase):

    docker run -d --rm --name emi-pg-teste -e POSTGRES_USER=teste \\
        -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=emi -p 55432:5432 postgres:16-alpine
    EMI_TESTE_MIGRACAO_URL=postgresql+asyncpg://teste:teste@localhost:55432/emi \\
        pytest tests/test_migracao_0011.py

NUNCA aponte esta variável para o Supabase.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.environ.get("EMI_TESTE_MIGRACAO_URL", "")
BACKEND = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not URL, reason="so contra Postgres descartavel: defina EMI_TESTE_MIGRACAO_URL"
)


def alembic(*args: str) -> None:
    """Roda o Alembic num processo à parte, apontado para o banco de teste.

    Processo à parte porque o `env.py` lê `settings.database_url`, que o conftest
    fixou num host inexistente de propósito.
    """
    env = {**os.environ, "DATABASE_URL": URL}
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stderr


@pytest.fixture
async def banco():
    alembic("downgrade", "base")
    alembic("upgrade", "0010")
    engine = create_async_engine(URL)
    try:
        yield engine
    finally:
        await engine.dispose()
        # Deixa o banco no head para o próximo uso (e para o test_rls, se apontado aqui).
        alembic("upgrade", "head")


async def consultar(engine, sql: str, **params) -> list:
    async with engine.connect() as conexao:
        return (await conexao.execute(text(sql), params)).all()


async def semear_0010(engine) -> None:
    """Dois usuários, cada um com um modelo; um com execução e refresh token."""
    async with engine.begin() as c:
        await c.execute(
            text(
                """
                INSERT INTO usuarios (id_usuario, nome, email, senha_hash, papel, criado_em)
                VALUES (1, 'Ana', 'ana.loja@exemplo.com', 'h', 'usuario_pme', '2026-09-01'),
                       (2, 'Bia', 'bia@outra.com', 'h', 'admin', '2026-09-02')
                """
            )
        )
        await c.execute(text("SELECT setval('usuarios_id_usuario_seq', 2)"))
        await c.execute(
            text(
                """
                INSERT INTO modelos_analise (id_modelo, id_usuario, nome, termo_pesquisa, filtros)
                VALUES (10, 1, 'Campanha Ana', '', '{"videos": ["a"]}'),
                       (11, 1, 'Outra da Ana', '', '{"videos": ["b"]}'),
                       (20, 2, 'Campanha Bia', '', '{"videos": ["c"]}')
                """
            )
        )
        await c.execute(text("INSERT INTO execucoes (id_modelo, status) VALUES (10, 'concluida')"))
        await c.execute(
            text(
                """
                INSERT INTO tokens_atualizacao (id_usuario, token_hash, expira_em)
                VALUES (1, repeat('a', 64), now() + interval '1 day')
                """
            )
        )


async def test_upgrade_faz_o_backfill_de_uma_empresa_por_usuario(banco):
    await semear_0010(banco)

    alembic("upgrade", "0011")

    empresas = await consultar(banco, "SELECT id_empresa, nome FROM empresas ORDER BY nome")
    assert [nome for _, nome in empresas] == ["ana.loja", "bia"]
    usuarios = await consultar(
        banco,
        """
        SELECT u.id_usuario, u.papel, u.papel_empresa, e.nome, e.criada_em::date
        FROM usuarios u JOIN empresas e USING (id_empresa) ORDER BY u.id_usuario
        """,
    )
    assert [(u[0], u[1], u[2], u[3]) for u in usuarios] == [
        (1, "usuario_pme", "dono", "ana.loja"),
        (2, "admin", "dono", "bia"),  # o papel global não muda
    ]
    assert str(usuarios[0][4]) == "2026-09-01"  # a empresa herda a data do cadastro

    modelos = await consultar(
        banco,
        """
        SELECT m.id_modelo, m.id_usuario, m.id_empresa = u.id_empresa
        FROM modelos_analise m JOIN usuarios u USING (id_usuario) ORDER BY m.id_modelo
        """,
    )
    assert modelos == [(10, 1, True), (11, 1, True), (20, 2, True)]
    # Ninguém passa a ver o que não via: cada empresa tem exatamente um membro.
    por_empresa = await consultar(
        banco, "SELECT count(*) FROM usuarios GROUP BY id_empresa HAVING count(*) > 1"
    )
    assert por_empresa == []


async def test_upgrade_deixa_colunas_obrigatorias_e_rls_ligado(banco):
    await semear_0010(banco)
    alembic("upgrade", "0011")

    nulas = await consultar(
        banco,
        """
        SELECT table_name, column_name, is_nullable FROM information_schema.columns
        WHERE (table_name, column_name) IN (('usuarios', 'id_empresa'),
            ('usuarios', 'papel_empresa'), ('modelos_analise', 'id_empresa'))
        ORDER BY 1, 2
        """,
    )
    assert {(t, c): n for t, c, n in nulas} == {
        ("modelos_analise", "id_empresa"): "NO",
        ("usuarios", "id_empresa"): "NO",
        ("usuarios", "papel_empresa"): "NO",
    }
    rls = await consultar(
        banco,
        """
        SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
        WHERE relname IN ('empresas', 'convites', 'tokens_redefinicao_senha')
        ORDER BY relname
        """,
    )
    assert rls == [
        ("convites", True, False),
        ("empresas", True, False),
        ("tokens_redefinicao_senha", True, False),
    ]


async def test_codigo_antigo_ainda_insere_refresh_token_depois_do_upgrade(banco):
    """No intervalo do deploy o código antigo grava refresh sem `substituido_em`."""
    await semear_0010(banco)
    alembic("upgrade", "0011")

    async with banco.begin() as c:
        await c.execute(
            text(
                "INSERT INTO tokens_atualizacao (id_usuario, token_hash, expira_em) "
                "VALUES (1, repeat('b', 64), now() + interval '1 day')"
            )
        )

    assert await consultar(banco, "SELECT count(*) FROM tokens_atualizacao") == [(2,)]


async def test_downgrade_com_dados_do_modelo_novo_volta_a_0010(banco):
    await semear_0010(banco)
    alembic("upgrade", "0011")
    # Dados que só existem no modelo novo: membro por convite, convite, link de senha,
    # refresh substituído.
    async with banco.begin() as c:
        await c.execute(
            text(
                """
                INSERT INTO usuarios (nome, email, senha_hash, papel, id_empresa, papel_empresa)
                SELECT 'Cris', 'cris@exemplo.com', 'h', 'usuario_pme', id_empresa, 'membro'
                FROM usuarios WHERE id_usuario = 1
                """
            )
        )
        await c.execute(
            text(
                """
                INSERT INTO convites (id_empresa, email, token_hash, papel_empresa, criado_por,
                    expira_em)
                SELECT id_empresa, 'dani@exemplo.com', repeat('c', 64), 'membro', 1,
                    now() + interval '7 days'
                FROM usuarios WHERE id_usuario = 1
                """
            )
        )
        await c.execute(
            text(
                "INSERT INTO tokens_redefinicao_senha (id_usuario, token_hash, expira_em) "
                "VALUES (1, repeat('d', 64), now() + interval '30 minutes')"
            )
        )
        await c.execute(text("UPDATE tokens_atualizacao SET substituido_em = now()"))

    alembic("downgrade", "0010")

    tabelas = await consultar(
        banco,
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('empresas', 'convites', 'tokens_redefinicao_senha')
        """,
    )
    assert tabelas == []
    colunas = await consultar(
        banco,
        """
        SELECT table_name, column_name FROM information_schema.columns
        WHERE column_name IN ('id_empresa', 'papel_empresa', 'substituido_em')
        """,
    )
    assert colunas == []
    # Contas e modelos sobrevivem; o membro por convite continua com a conta.
    assert await consultar(banco, "SELECT count(*) FROM usuarios") == [(3,)]
    assert await consultar(banco, "SELECT count(*) FROM modelos_analise") == [(3,)]
    assert await consultar(banco, "SELECT count(*) FROM execucoes") == [(1,)]

    # E sobe de novo: o backfill roda outra vez, agora com três usuários.
    alembic("upgrade", "head")
    assert await consultar(banco, "SELECT count(*) FROM empresas") == [(3,)]
