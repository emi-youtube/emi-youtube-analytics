"""Migração 0012 (aceites_termos) e a exclusão de conta, contra Postgres de verdade.

**DESTRUTIVO: só contra um banco descartável**, como `test_migracao_0011.py`:

    docker run -d --rm --name emi-pg-teste -e POSTGRES_USER=teste \\
        -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=emi -p 55432:5432 postgres:16-alpine
    EMI_TESTE_MIGRACAO_URL=postgresql+asyncpg://teste:teste@localhost:55432/emi \\
        pytest tests/test_migracao_0012.py

A exclusão de conta também roda aqui, e não só no SQLite: é o Postgres que diz se
a ordem dos DELETEs respeita as chaves estrangeiras SEM cascata e se as com cascata
(`videos` -> `comentarios` -> `analises_sentimento`) apagam o que prometem.

NUNCA aponte esta variável para o Supabase.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.models.usuario import Usuario
from app.services import conta as conta_service
from tests.test_migracao_0011 import alembic

URL = os.environ.get("EMI_TESTE_MIGRACAO_URL", "")

pytestmark = pytest.mark.skipif(
    not URL, reason="so contra Postgres descartavel: defina EMI_TESTE_MIGRACAO_URL"
)

SENHA = "SenhaForte123"


@pytest.fixture
async def banco():
    alembic("downgrade", "base")
    alembic("upgrade", "0011")
    engine = create_async_engine(URL)
    try:
        yield engine
    finally:
        alembic("upgrade", "head")
        # Esvazia o que o teste gravou: um downgrade posterior (o desta fixture ou o da
        # 0011) falharia com dados que o schema antigo não aceita, como
        # `exemplos_treinamento.split` nulo diante da 0007.
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


async def consultar(engine, sql: str) -> list:
    async with engine.connect() as conexao:
        return (await conexao.execute(text(sql))).all()


async def executar(engine, *comandos: str) -> None:
    async with engine.begin() as conexao:
        for comando in comandos:
            await conexao.execute(text(comando))


async def semear_0011(engine) -> None:
    """Uma empresa com um usuário: a conta que existia antes do aceite."""
    await executar(
        engine,
        "INSERT INTO empresas (id_empresa, nome) VALUES (1, 'Loja')",
        """
        INSERT INTO usuarios (id_usuario, nome, email, senha_hash, papel, id_empresa,
                              papel_empresa)
        VALUES (1, 'Ana', 'ana@loja.com', 'h', 'usuario_pme', 1, 'dono')
        """,
    )


async def test_upgrade_nao_faz_backfill_e_liga_rls(banco):
    await semear_0011(banco)

    alembic("upgrade", "0012")

    # Conta antiga nasce PENDENTE: aceite é ato da pessoa, não da migração.
    assert await consultar(banco, "SELECT count(*) FROM aceites_termos") == [(0,)]
    rls = await consultar(
        banco,
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'aceites_termos'",
    )
    assert rls == [(True, False)]


async def test_um_aceite_por_versao_e_sai_com_o_usuario(banco):
    await semear_0011(banco)
    alembic("upgrade", "0012")
    await executar(
        banco, "INSERT INTO aceites_termos (id_usuario, versao_termos) VALUES (1, '1.0')"
    )

    with pytest.raises(Exception, match="uq_aceites_termos_usuario_versao"):
        await executar(
            banco, "INSERT INTO aceites_termos (id_usuario, versao_termos) VALUES (1, '1.0')"
        )
    await executar(banco, "DELETE FROM usuarios WHERE id_usuario = 1")
    assert await consultar(banco, "SELECT count(*) FROM aceites_termos") == [(0,)]


async def test_downgrade_com_aceites_volta_a_0011(banco):
    await semear_0011(banco)
    alembic("upgrade", "0012")
    await executar(
        banco, "INSERT INTO aceites_termos (id_usuario, versao_termos) VALUES (1, '1.0')"
    )

    alembic("downgrade", "0011")

    tabelas = await consultar(
        banco, "SELECT count(*) FROM pg_class WHERE relname = 'aceites_termos'"
    )
    assert tabelas == [(0,)]
    assert await consultar(banco, "SELECT count(*) FROM usuarios") == [(1,)]


# Toda tabela abaixo de uma empresa, para a fotografia antes/depois.
TABELAS = (
    "empresas",
    "usuarios",
    "aceites_termos",
    "convites",
    "tokens_atualizacao",
    "modelos_analise",
    "execucoes",
    "jobs",
    "jobs_dlq",
    "videos",
    "comentarios",
    "analises_sentimento",
    "temas",
    "comentario_tema",
    "exemplos_treinamento",
    "versoes_modelo",
)


async def fotografia(engine) -> dict[str, int]:
    return {t: (await consultar(engine, f"SELECT count(*) FROM {t}"))[0][0] for t in TABELAS}


async def semear_empresa(engine, n: int) -> None:
    """Empresa `n` com dono, aceite, convite, refresh e uma análise completa.

    Os ids são derivados de `n` para as duas empresas não colidirem.
    """
    senha_hash = hash_password(SENHA)
    await executar(
        engine,
        f"INSERT INTO empresas (id_empresa, nome) VALUES ({n}, 'Empresa {n}')",
        f"""
        INSERT INTO usuarios (id_usuario, nome, email, senha_hash, papel, id_empresa,
                              papel_empresa)
        VALUES ({n}, 'Dono {n}', 'dono{n}@x.com', '{senha_hash}', 'usuario_pme', {n}, 'dono')
        """,
        f"INSERT INTO aceites_termos (id_usuario, versao_termos) VALUES ({n}, '1.0')",
        f"""
        INSERT INTO convites (id_empresa, email, token_hash, papel_empresa, criado_por,
                              expira_em)
        VALUES ({n}, 'c{n}@x.com', repeat('{n}', 64), 'membro', {n}, now() + interval '1 day')
        """,
        f"""
        INSERT INTO tokens_atualizacao (id_usuario, token_hash, expira_em)
        VALUES ({n}, repeat('t{n}', 32), now() + interval '1 day')
        """,
        f"""
        INSERT INTO modelos_analise (id_modelo, id_usuario, id_empresa, nome, termo_pesquisa,
                                     filtros)
        VALUES ({n}, {n}, {n}, 'Campanha {n}', '', '{{"videos": ["v"]}}')
        """,
        f"INSERT INTO execucoes (id_execucao, id_modelo, status) VALUES ({n}, {n}, 'concluida')",
        f"INSERT INTO jobs (tipo, id_execucao, status) VALUES ('coleta', {n}, 'concluida')",
        f"INSERT INTO jobs_dlq (tipo, id_execucao, erro) VALUES ('topicos', {n}, 'x')",
        f"""
        INSERT INTO videos (id_video, id_execucao, youtube_video_id, titulo, canal)
        VALUES ({n}, {n}, 'v', 'Anúncio', 'Canal')
        """,
        f"""
        INSERT INTO comentarios (id_comentario, id_video, youtube_comment_id, autor_hash, texto)
        VALUES ({n}, {n}, 'c{n}', repeat('a', 64), 'comentário')
        """,
        f"""
        INSERT INTO analises_sentimento (id_comentario, id_versao_modelo, sentimento)
        VALUES ({n}, 1, 'positivo')
        """,
        f"""
        INSERT INTO temas (id_tema, id_execucao, rotulo_tema, palavras_chave)
        VALUES ({n}, {n}, 'preço', '["caro"]')
        """,
        f"INSERT INTO comentario_tema (id_comentario, id_tema, peso) VALUES ({n}, {n}, 0.5)",
        f"""
        INSERT INTO exemplos_treinamento (id_comentario, texto, rotulo_fraco)
        VALUES ({n}, 'comentário', 'positivo')
        """,
    )


async def test_exclusao_do_dono_unico_no_postgres_nao_toca_outra_empresa(banco):
    alembic("upgrade", "head")
    await executar(
        banco,
        "INSERT INTO versoes_modelo (id_versao, nome_modelo, versao, status) "
        "VALUES (1, 'lexico', '1.0.0', 'ativo')",
    )
    await semear_empresa(banco, 2)
    so_a_outra = await fotografia(banco)
    await semear_empresa(banco, 1)

    fabrica = async_sessionmaker(banco, expire_on_commit=False)
    async with fabrica() as sessao:
        usuario = await sessao.get(Usuario, 1)
        await conta_service.excluir_conta(sessao, usuario, SENHA)

    depois = await fotografia(banco)
    # O corpus de treino é do projeto (ADR-012): o exemplo fica, sem a referência.
    assert depois.pop("exemplos_treinamento") == so_a_outra.pop("exemplos_treinamento") + 1
    assert depois == so_a_outra
    orfaos = await consultar(
        banco, "SELECT count(*) FROM exemplos_treinamento WHERE id_comentario IS NULL"
    )
    assert orfaos == [(1,)]
