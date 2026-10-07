"""Fixtures dos testes de autenticação.

As variáveis de ambiente são forçadas ANTES de importar `app`, por dois motivos:
1. DATABASE_URL aponta para um host inexistente — assim um teste jamais consegue
   escrever no Supabase compartilhado, mesmo que o override de `get_db` falhe;
2. o segredo do JWT e os prazos ficam fixos, então o teste não depende do .env local.

O banco dos testes é SQLite em memória, com só as tabelas que os testes exercitam
(`TABELAS_TESTADAS`). As colunas JSONB são declaradas com `with_variant`, então
viram JSON no SQLite e as tabelas podem ser criadas aqui.
"""

import logging
import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://testes:testes@localhost:1/banco-inexistente"
os.environ["JWT_SECRET_KEY"] = "segredo-exclusivo-dos-testes-0123456789abcdef"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
os.environ["JWT_REFRESH_TOKEN_EXPIRE_DAYS"] = "7"
os.environ["YOUTUBE_API_KEY"] = "chave-de-teste"

from typing import Annotated
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import requer_admin
from app.api.v1.auth import limite_cadastro, limite_emails_cadastro, limite_esqueci_senha
from app.core.database import Base, get_db
from app.main import app
from app.models.aceite_termos import AceiteTermos
from app.models.analise_sentimento import AnaliseSentimento
from app.models.cadastro_pendente import CadastroPendente
from app.models.comentario import Comentario
from app.models.comentario_tema import ComentarioTema
from app.models.convite import Convite
from app.models.empresa import Empresa
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.token_redefinicao_senha import TokenRedefinicaoSenha
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video
from app.services import email as email_service

TABELAS_TESTADAS = [
    Empresa.__table__,
    Usuario.__table__,
    AceiteTermos.__table__,
    CadastroPendente.__table__,
    Convite.__table__,
    TokenAtualizacao.__table__,
    TokenRedefinicaoSenha.__table__,
    TentativaLogin.__table__,
    ModeloAnalise.__table__,
    Execucao.__table__,
    Job.__table__,
    JobDlq.__table__,
    Video.__table__,
    Comentario.__table__,
    VersaoModelo.__table__,
    AnaliseSentimento.__table__,
    Tema.__table__,
    ComentarioTema.__table__,
]

ROTA_ADMIN = "/api/v1/_teste/somente-admin"


# O CRUD ainda não existe, então a rota protegida por `requer_admin` só existe no teste.
@app.get(ROTA_ADMIN)
async def _rota_somente_admin(usuario: Annotated[Usuario, Depends(requer_admin)]) -> dict:
    return {"papel": usuario.papel}


@pytest.fixture(autouse=True)
def _preservar_log_raiz():
    """O arranque da API configura o log raiz (core/logs.py); um teste que roda o
    `lifespan` não pode deixar o raiz em INFO para os seguintes, cujo `caplog`
    passaria a receber linhas de outros loggers."""
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    niveis = {nome: logging.getLogger(nome).level for nome in ("httpx", "httpcore")}
    yield
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)
    for nome, valor in niveis.items():
        logging.getLogger(nome).setLevel(valor)


@pytest.fixture(autouse=True)
def _zerar_limite_esqueci_senha():
    """O limite por IP é estado do processo: sem zerar, um teste herdaria o do outro."""
    limites = (limite_esqueci_senha, limite_cadastro, limite_emails_cadastro)
    for limite in limites:
        limite.limpar()
    yield
    for limite in limites:
        limite.limpar()


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


def token_do_email(texto: str) -> str | None:
    """O token de um e-mail com link `...?token=<token>`, ou None se não houver link."""
    if "token=" not in texto:
        return None
    return texto.split("token=")[1].split()[0]


async def pedir_e_confirmar_cadastro(
    cliente, email: str, senha: str = "SenhaForte123", nome_empresa: str | None = None
):
    """Cadastro de empresa nova de ponta a ponta (ADR-014): pede, lê o e-mail, confirma.

    Intercepta o envio só durante o pedido, sem repassar: o e-mail de confirmação não
    aparece na caixa de saída que o próprio teste tenha montado. Devolve a resposta do
    `confirmar-cadastro` (com os tokens), ou None se o e-mail já tinha conta.
    """
    capturados: list[tuple[str, str, str]] = []

    async def capturar(destinatario: str, assunto: str, texto: str) -> None:
        capturados.append((destinatario, assunto, texto))

    original = email_service.enviar
    email_service.enviar = capturar
    try:
        pedido = await cliente.post(
            "/api/v1/auth/registrar",
            json={
                "nome": f"Conta {email}",
                "email": email,
                "senha": senha,
                "nome_empresa": nome_empresa or f"Empresa de {email}",
                "aceite_termos": True,
            },
        )
    finally:
        email_service.enviar = original
    assert pedido.status_code == 202, pedido.text

    token = token_do_email(capturados[-1][2]) if capturados else None
    if token is None:
        return None
    return await cliente.post("/api/v1/auth/confirmar-cadastro", json={"token": token})


async def autenticar(cliente, email: str, senha: str = "SenhaForte123") -> dict[str, str]:
    """Cria a conta (dono de uma empresa nova), loga e devolve o header Authorization."""
    await pedir_e_confirmar_cadastro(cliente, email, senha)
    resposta = await cliente.post("/api/v1/auth/login", json={"email": email, "senha": senha})
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


def token_do_link(link: str) -> str:
    """Extrai o token de um link de convite (`.../entrar?convite=<token>`)."""
    return parse_qs(urlparse(link).query)["convite"][0]


async def convidar(
    cliente, cabecalho_dono: dict[str, str], email: str, papel_empresa: str = "membro"
) -> str:
    """O dono convida `email`; devolve o token do convite."""
    resposta = await cliente.post(
        "/api/v1/empresa/convites",
        json={"email": email, "papel_empresa": papel_empresa},
        headers=cabecalho_dono,
    )
    assert resposta.status_code == 201, resposta.text
    return token_do_link(resposta.json()["link"])


async def autenticar_convidado(
    cliente,
    cabecalho_dono: dict[str, str],
    email: str,
    senha: str = "SenhaForte123",
    papel_empresa: str = "membro",
) -> dict[str, str]:
    """Convida, registra pelo convite, loga e devolve o header do novo membro."""
    token = await convidar(cliente, cabecalho_dono, email, papel_empresa)
    registro = await cliente.post(
        "/api/v1/auth/registrar",
        json={
            "nome": f"Conta {email}",
            "email": email,
            "senha": senha,
            "token_convite": token,
            "aceite_termos": True,
        },
    )
    assert registro.status_code == 201, registro.text
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
