"""Migração 0015 (guarda dos dados do YouTube) e o expurgo, contra Postgres de verdade.

**DESTRUTIVO: só contra um banco descartável**, como `test_migracao_0011.py`:

    EMI_TESTE_MIGRACAO_URL=postgresql+asyncpg://teste:teste@localhost:55432/emi \\
        pytest tests/test_migracao_0015.py

O expurgo roda aqui também, e não só no SQLite: os `UPDATE ... WHERE ... IN (SELECT ...)`
e a exclusão em cascata dos 36 meses são do Postgres que roda em produção.

NUNCA aponte esta variável para o Supabase.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.workers import expurgo
from tests.test_migracao_0011 import alembic

URL = os.environ.get("EMI_TESTE_MIGRACAO_URL", "")

pytestmark = pytest.mark.skipif(
    not URL, reason="so contra Postgres descartavel: defina EMI_TESTE_MIGRACAO_URL"
)

INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def banco():
    alembic("downgrade", "base")
    alembic("upgrade", "0014")
    engine = create_async_engine(URL)
    try:
        yield engine
    finally:
        async with engine.begin() as conexao:
            tabelas = await conexao.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version'"
                )
            )
            nomes = ", ".join(f'public."{nome}"' for (nome,) in tabelas)
            await conexao.execute(text(f"TRUNCATE {nomes} RESTART IDENTITY CASCADE"))
        await engine.dispose()
        alembic("upgrade", "head")


async def consultar(engine, sql: str) -> list:
    async with engine.connect() as conexao:
        return (await conexao.execute(text(sql))).all()


async def executar(engine, *comandos: str, **params) -> None:
    async with engine.begin() as conexao:
        for comando in comandos:
            await conexao.execute(text(comando), params)


async def semear_0014(engine) -> None:
    """Empresa -> usuário -> modelo -> execução de 01/09 -> vídeo -> 2 comentários analisados."""
    await executar(
        engine,
        "INSERT INTO empresas (id_empresa, nome) VALUES (1, 'Loja')",
        """
        INSERT INTO usuarios (id_usuario, nome, email, senha_hash, papel, id_empresa,
                              papel_empresa)
        VALUES (1, 'Ana', 'ana@loja.com', 'h', 'usuario_pme', 1, 'dono')
        """,
        """
        INSERT INTO modelos_analise (id_modelo, id_usuario, id_empresa, nome, termo_pesquisa,
                                     filtros)
        VALUES (1, 1, 1, 'Campanha', '', '{"videos": ["v1"]}')
        """,
        """
        INSERT INTO execucoes (id_execucao, id_modelo, status, iniciado_em, concluido_em)
        VALUES (1, 1, 'concluida', :inicio, :inicio)
        """,
        """
        INSERT INTO videos (id_video, id_execucao, youtube_video_id, titulo, canal)
        VALUES (1, 1, 'v1', 'Anúncio', 'Loja')
        """,
        """
        INSERT INTO comentarios (id_comentario, id_video, youtube_comment_id, autor_hash, texto)
        VALUES (1, 1, 'c1', 'hash1', 'adorei'), (2, 1, 'c2', 'hash2', 'caro demais')
        """,
        """
        INSERT INTO versoes_modelo (id_versao, nome_modelo, versao, status)
        VALUES (1, 'bertimbau-emi', '1.0.0', 'ativo')
        """,
        """
        INSERT INTO analises_sentimento (id_comentario, id_versao_modelo, sentimento,
                                         justificativa)
        VALUES (1, 1, 'positivo', 'cita adorei'), (2, 1, 'negativo', NULL)
        """,
        """
        INSERT INTO temas (id_tema, id_execucao, rotulo_tema) VALUES (1, 1, 'preço')
        """,
        "INSERT INTO comentario_tema (id_comentario, id_tema, peso) VALUES (2, 1, 0.9)",
        inicio=INICIO,
    )


async def test_upgrade_herda_a_data_da_coleta_e_libera_o_nulo(banco):
    await semear_0014(banco)

    alembic("upgrade", "0015")

    assert await consultar(banco, "SELECT metadados_em FROM videos") == [(INICIO,)]
    nulos = await consultar(
        banco,
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_name = 'comentarios' "
        "AND column_name IN ('texto', 'autor_hash', 'youtube_comment_id') ORDER BY 1",
    )
    assert nulos == [("autor_hash", "YES"), ("texto", "YES"), ("youtube_comment_id", "YES")]


async def test_expurgo_no_postgres_apaga_o_texto_e_mantem_o_resultado(banco):
    await semear_0014(banco)
    alembic("upgrade", "0015")

    async with async_sessionmaker(banco, expire_on_commit=False)() as sessao:
        apagadas = await expurgo.apagar_comentarios_vencidos(sessao, INICIO + timedelta(days=30))
        videos_apagados = await expurgo.apagar_videos_vencidos(sessao, INICIO + timedelta(days=30))

    assert apagadas == [1]
    assert videos_apagados == 1
    assert await consultar(
        banco, "SELECT texto, autor_hash, youtube_comment_id FROM comentarios ORDER BY 1"
    ) == [(None, None, None), (None, None, None)]
    assert await consultar(
        banco, "SELECT count(*), count(justificativa) FROM analises_sentimento"
    ) == [(2, 0)]
    assert await consultar(banco, "SELECT count(*) FROM comentario_tema") == [(1,)]
    assert await consultar(banco, "SELECT titulo, canal, metadados_em FROM videos") == [
        ("", "", None)
    ]
    assert (await consultar(banco, "SELECT comentarios_apagados_em FROM execucoes"))[0][0]


async def test_36_meses_apaga_em_cascata_no_postgres(banco):
    await semear_0014(banco)
    alembic("upgrade", "0015")
    await executar(
        banco,
        "INSERT INTO jobs (tipo, id_execucao, status) VALUES ('topicos', 1, 'concluida')",
    )

    async with async_sessionmaker(banco, expire_on_commit=False)() as sessao:
        apagadas = await expurgo.apagar_resultados_vencidos(sessao, INICIO + timedelta(days=1100))

    assert apagadas == [1]
    for tabela in ("execucoes", "videos", "comentarios", "analises_sentimento", "temas", "jobs"):
        assert await consultar(banco, f"SELECT count(*) FROM {tabela}") == [(0,)], tabela
    assert await consultar(banco, "SELECT count(*) FROM modelos_analise") == [(1,)]


async def test_downgrade_recusa_quando_o_texto_ja_foi_apagado(banco):
    await semear_0014(banco)
    alembic("upgrade", "0015")
    await executar(banco, "UPDATE comentarios SET texto = NULL WHERE id_comentario = 1")

    with pytest.raises(AssertionError, match="expurgo"):
        alembic("downgrade", "0014")

    await executar(banco, "UPDATE comentarios SET texto = 'volta' WHERE id_comentario = 1")
    alembic("downgrade", "0014")
    assert await consultar(banco, "SELECT count(*) FROM comentarios") == [(2,)]
