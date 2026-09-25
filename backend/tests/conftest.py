"""Fixtures dos testes de autenticação.

As variáveis de ambiente são forçadas ANTES de importar `app`, por dois motivos:
1. DATABASE_URL aponta para um host inexistente — assim um teste jamais consegue
   escrever no Supabase compartilhado, mesmo que o override de `get_db` falhe;
2. o segredo do JWT e os prazos ficam fixos, então o teste não depende do .env local.

O banco dos testes é SQLite em memória, com só as tabelas que os testes exercitam
(`TABELAS_TESTADAS`). As colunas JSONB são declaradas com `with_variant`, então
viram JSON no SQLite e as tabelas podem ser criadas aqui.
"""

import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://testes:testes@localhost:1/banco-inexistente"
os.environ["JWT_SECRET_KEY"] = "segredo-exclusivo-dos-testes-0123456789abcdef"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
os.environ["JWT_REFRESH_TOKEN_EXPIRE_DAYS"] = "7"
os.environ["YOUTUBE_API_KEY"] = "chave-de-teste"

from typing import Annotated

import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import requer_admin
from app.core.database import Base, get_db
from app.main import app
from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video

TABELAS_TESTADAS = [
    Usuario.__table__,
    TokenAtualizacao.__table__,
    TentativaLogin.__table__,
    ModeloAnalise.__table__,
    Execucao.__table__,
    Job.__table__,
    JobDlq.__table__,
    Video.__table__,
    Comentario.__table__,
    VersaoModelo.__table__,
    AnaliseSentimento.__table__,
]

ROTA_ADMIN = "/api/v1/_teste/somente-admin"


# O CRUD ainda não existe, então a rota protegida por `requer_admin` só existe no teste.
@app.get(ROTA_ADMIN)
async def _rota_somente_admin(usuario: Annotated[Usuario, Depends(requer_admin)]) -> dict:
    return {"papel": usuario.papel}


@pytest_asyncio.fixture
async def engine_teste():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    # O SQLite ignora FOREIGN KEY por padrão; sem isso as restrições de integridade
    # do schema não seriam exercitadas em teste nenhum.
    @event.listens_for(engine.sync_engine, "connect")
    def _ativar_foreign_keys(conexao, _):
        cursor = conexao.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=TABELAS_TESTADAS)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def sessao(engine_teste):
    async with async_sessionmaker(engine_teste, expire_on_commit=False)() as s:
        yield s


async def autenticar(cliente, email: str, senha: str = "SenhaForte123") -> dict[str, str]:
    """Registra, loga e devolve o header Authorization pronto para uso."""
    await cliente.post(
        "/api/v1/auth/registrar", json={"nome": f"Conta {email}", "email": email, "senha": senha}
    )
    resposta = await cliente.post("/api/v1/auth/login", json={"email": email, "senha": senha})
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


@pytest_asyncio.fixture
async def cliente(engine_teste):
    fabrica = async_sessionmaker(engine_teste, expire_on_commit=False)

    async def _get_db():
        async with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as c:
        yield c
    app.dependency_overrides.clear()
