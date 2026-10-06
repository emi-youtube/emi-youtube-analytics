"""Termos de Uso e direitos do titular sobre a própria conta (ADR-012)."""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core import config
from app.core.security import hash_token
from app.models.aceite_termos import AceiteTermos
from app.models.analise_sentimento import AnaliseSentimento
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
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video
from app.services.auth import MAX_TENTATIVAS
from app.services.conta import DONO_COM_MEMBROS, EXECUCAO_EM_ANDAMENTO
from tests.conftest import autenticar, autenticar_convidado, convidar

SENHA = "SenhaForte123"
DONA = "dona@loja.com"
MEMBRO = "membro@loja.com"
OUTRA = "dona@concorrente.com"

# Toda tabela que guarda algo de uma empresa. `versoes_modelo` entra para provar
# que a exclusão NÃO a toca: é compartilhada entre empresas.
TABELAS = {
    "empresas": Empresa,
    "usuarios": Usuario,
    "aceites_termos": AceiteTermos,
    "convites": Convite,
    "tokens_atualizacao": TokenAtualizacao,
    "modelos_analise": ModeloAnalise,
    "execucoes": Execucao,
    "jobs": Job,
    "jobs_dlq": JobDlq,
    "videos": Video,
    "comentarios": Comentario,
    "analises_sentimento": AnaliseSentimento,
    "temas": Tema,
    "comentario_tema": ComentarioTema,
    "versoes_modelo": VersaoModelo,
}


async def contagens(sessao) -> dict[str, int]:
    # A sessão do teste é outra que a da API: sem expirar, leria o cache.
    sessao.expire_all()
    return {
        nome: await sessao.scalar(select(func.count()).select_from(modelo))
        for nome, modelo in TABELAS.items()
    }


async def usuario_por_email(sessao, email: str) -> Usuario | None:
    sessao.expire_all()
    return await sessao.scalar(select(Usuario).where(Usuario.email == email))


async def semear_analise(sessao, email: str, *, status: str = "concluida") -> Execucao:
    """Modelo criado por `email` -> execução -> job, DLQ, vídeo, comentários,
    análises, tema e comentario_tema: uma linha em cada tabela abaixo da empresa."""
    usuario = await usuario_por_email(sessao, email)
    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario,
        id_empresa=usuario.id_empresa,
        nome=f"Campanha de {email}",
        termo_pesquisa="tênis",
        filtros={"videos": ["v1"]},
    )
    sessao.add(modelo)
    await sessao.flush()
    execucao = Execucao(
        id_modelo=modelo.id_modelo, status=status, iniciado_em=datetime(2026, 10, 1, tzinfo=UTC)
    )
    sessao.add(execucao)
    await sessao.flush()
    sessao.add_all(
        [
            Job(tipo="coleta", id_execucao=execucao.id_execucao, status="concluida"),
            JobDlq(tipo="topicos", id_execucao=execucao.id_execucao, erro="falhou"),
        ]
    )
    video = Video(
        id_execucao=execucao.id_execucao, youtube_video_id="v1", titulo="Anúncio", canal="Loja"
    )
    sessao.add(video)
    await sessao.flush()

    versao = await sessao.scalar(select(VersaoModelo).where(VersaoModelo.versao == "1.0.0"))
    if versao is None:
        versao = VersaoModelo(nome_modelo="lexico", versao="1.0.0", status="ativo")
        sessao.add(versao)
        await sessao.flush()

    tema = Tema(id_execucao=execucao.id_execucao, rotulo_tema="preço", palavras_chave=["caro"])
    sessao.add(tema)
    await sessao.flush()
    for indice, sentimento in enumerate(("positivo", "negativo")):
        comentario = Comentario(
            id_video=video.id_video,
            youtube_comment_id=f"{email}-{indice}",
            autor_hash=hash_token(f"autor{indice}"),
            texto="comentário de teste",
        )
        sessao.add(comentario)
        await sessao.flush()
        sessao.add_all(
            [
                AnaliseSentimento(
                    id_comentario=comentario.id_comentario,
                    id_versao_modelo=versao.id_versao,
                    sentimento=sentimento,
                ),
                ComentarioTema(
                    id_comentario=comentario.id_comentario, id_tema=tema.id_tema, peso=0.5
                ),
            ]
        )
    await sessao.commit()
    return execucao


async def excluir(cliente, cabecalho, senha: str = SENHA):
    return await cliente.request(
        "DELETE", "/api/v1/conta", json={"senha": senha}, headers=cabecalho
    )


# --------------------------------------------------------------------------- cadastro


async def test_cadastro_sem_aceite_responde_422_ao_criar_empresa(cliente, sessao):
    corpo = {"nome": "Dona", "email": DONA, "senha": SENHA, "nome_empresa": "Loja"}

    ausente = await cliente.post("/api/v1/auth/registrar", json=corpo)
    falso = await cliente.post("/api/v1/auth/registrar", json={**corpo, "aceite_termos": False})

    assert ausente.status_code == 422
    assert falso.status_code == 422
    assert (await contagens(sessao))["usuarios"] == 0
    assert (await contagens(sessao))["empresas"] == 0


async def test_cadastro_sem_aceite_responde_422_por_convite(cliente, sessao):
    dona = await autenticar(cliente, DONA)
    token = await convidar(cliente, dona, MEMBRO)
    corpo = {"nome": "Membro", "email": MEMBRO, "senha": SENHA, "token_convite": token}

    ausente = await cliente.post("/api/v1/auth/registrar", json=corpo)
    falso = await cliente.post("/api/v1/auth/registrar", json={**corpo, "aceite_termos": False})

    assert ausente.status_code == 422
    assert falso.status_code == 422
    assert await usuario_por_email(sessao, MEMBRO) is None
    # O convite não foi consumido: o 422 vem antes de qualquer escrita.
    sessao.expire_all()
    convite = await sessao.scalar(select(Convite).where(Convite.email == MEMBRO))
    assert convite.usado_em is None


async def test_cadastro_com_aceite_grava_versao_e_data(cliente, sessao):
    dona = await autenticar(cliente, DONA)
    await autenticar_convidado(cliente, dona, MEMBRO)

    for email in (DONA, MEMBRO):
        usuario = await usuario_por_email(sessao, email)
        aceites = (
            await sessao.scalars(
                select(AceiteTermos).where(AceiteTermos.id_usuario == usuario.id_usuario)
            )
        ).all()
        assert [a.versao_termos for a in aceites] == [config.VERSAO_TERMOS]
        assert aceites[0].aceito_em is not None


# --------------------------------------------------------------------------- pendência


async def test_termos_pendentes_ate_o_aceite_e_de_novo_com_versao_nova(
    cliente, sessao, monkeypatch
):
    cabecalho = await autenticar(cliente, DONA)
    usuario = await usuario_por_email(sessao, DONA)
    # Conta antiga, de antes da 0012: sem aceite nenhum (a migração não faz backfill).
    await sessao.execute(
        AceiteTermos.__table__.delete().where(AceiteTermos.id_usuario == usuario.id_usuario)
    )
    await sessao.commit()

    eu = await cliente.get("/api/v1/auth/eu", headers=cabecalho)
    assert eu.json()["termos_pendentes"] is True

    assert (
        await cliente.post("/api/v1/conta/aceitar-termos", headers=cabecalho)
    ).status_code == 204
    eu = await cliente.get("/api/v1/auth/eu", headers=cabecalho)
    assert eu.json()["termos_pendentes"] is False

    monkeypatch.setattr(config, "VERSAO_TERMOS", "2.0")
    eu = await cliente.get("/api/v1/auth/eu", headers=cabecalho)
    assert eu.json()["termos_pendentes"] is True


async def test_aceitar_termos_e_idempotente(cliente, sessao):
    cabecalho = await autenticar(cliente, DONA)

    for _ in range(2):
        resposta = await cliente.post("/api/v1/conta/aceitar-termos", headers=cabecalho)
        assert resposta.status_code == 204

    assert (await contagens(sessao))["aceites_termos"] == 1


async def test_rotas_da_conta_exigem_token(cliente):
    assert (await cliente.post("/api/v1/conta/aceitar-termos")).status_code == 401
    assert (await cliente.get("/api/v1/conta/meus-dados")).status_code == 401
    assert (await excluir(cliente, {})).status_code == 401


# --------------------------------------------------------------------------- meus dados


async def test_meus_dados_traz_o_cadastro_aceites_e_modelos(cliente, sessao):
    cabecalho = await autenticar(cliente, DONA)
    await semear_analise(sessao, DONA)

    resposta = await cliente.get("/api/v1/conta/meus-dados", headers=cabecalho)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["email"] == DONA
    assert corpo["empresa"] == {"nome": f"Empresa de {DONA}"}
    assert corpo["papel_empresa"] == "dono"
    assert [a["versao_termos"] for a in corpo["aceites_termos"]] == [config.VERSAO_TERMOS]
    assert [m["nome"] for m in corpo["modelos_criados"]] == [f"Campanha de {DONA}"]


async def test_meus_dados_sem_credencial_e_sem_dados_de_colegas(cliente, sessao):
    dona = await autenticar(cliente, DONA)
    membro = await autenticar_convidado(cliente, dona, MEMBRO)
    await semear_analise(sessao, DONA)

    resposta = await cliente.get("/api/v1/conta/meus-dados", headers=membro)
    texto = resposta.text
    hash_dona = (await usuario_por_email(sessao, DONA)).senha_hash
    hash_membro = (await usuario_por_email(sessao, MEMBRO)).senha_hash

    assert resposta.json()["email"] == MEMBRO
    # O modelo é da empresa, mas foi a dona quem o criou: não é dado do membro.
    assert resposta.json()["modelos_criados"] == []
    # O nome da empresa contém o e-mail da dona (helper `autenticar`); o que não pode
    # aparecer é o CADASTRO dela.
    assert f"Conta {DONA}" not in texto
    assert f'"email":"{DONA}"' not in texto
    assert "senha" not in texto
    assert "token" not in texto
    assert hash_membro not in texto
    assert hash_dona not in texto


# --------------------------------------------------------------------------- exclusão


async def test_membro_excluido_transfere_modelos_e_preserva_execucoes(cliente, sessao):
    dona = await autenticar(cliente, DONA)
    membro = await autenticar_convidado(cliente, dona, MEMBRO)
    id_modelo = (await semear_analise(sessao, MEMBRO)).id_modelo
    antes = await contagens(sessao)
    id_dona = (await usuario_por_email(sessao, DONA)).id_usuario

    resposta = await excluir(cliente, membro)

    assert resposta.status_code == 204, resposta.text
    assert await usuario_por_email(sessao, MEMBRO) is None
    depois = await contagens(sessao)
    assert depois["usuarios"] == antes["usuarios"] - 1
    assert depois["aceites_termos"] == antes["aceites_termos"] - 1
    for tabela in ("empresas", "modelos_analise", "execucoes", "comentarios", "temas"):
        assert depois[tabela] == antes[tabela], tabela
    modelo = await sessao.scalar(select(ModeloAnalise).where(ModeloAnalise.id_modelo == id_modelo))
    assert modelo.id_usuario == id_dona


async def test_dono_unico_apaga_a_empresa_inteira_e_nada_de_outra(cliente, sessao):
    """Teste de mutação: a outra empresa é semeada primeiro e fotografada; depois de
    apagar a primeira, o banco tem de voltar EXATAMENTE à fotografia — nada da
    empresa apagada sobra, nada da outra some."""
    await autenticar(cliente, OUTRA)
    await semear_analise(sessao, OUTRA)
    so_a_outra = await contagens(sessao)

    dona = await autenticar(cliente, DONA)
    await semear_analise(sessao, DONA)
    await convidar(cliente, dona, "pendente@loja.com")
    com_as_duas = await contagens(sessao)
    assert all(com_as_duas[t] > so_a_outra[t] for t in TABELAS if t != "versoes_modelo")

    resposta = await excluir(cliente, dona)

    assert resposta.status_code == 204, resposta.text
    assert await contagens(sessao) == so_a_outra


async def test_dono_com_membros_responde_409_e_nada_apagado(cliente, sessao):
    dona = await autenticar(cliente, DONA)
    await autenticar_convidado(cliente, dona, MEMBRO)
    await semear_analise(sessao, DONA)
    antes = await contagens(sessao)

    resposta = await excluir(cliente, dona)

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == DONO_COM_MEMBROS
    assert await contagens(sessao) == antes


async def test_execucao_em_andamento_responde_409_e_nada_apagado(cliente, sessao):
    dona = await autenticar(cliente, DONA)
    await semear_analise(sessao, DONA, status="processando")
    antes = await contagens(sessao)

    resposta = await excluir(cliente, dona)

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == EXECUCAO_EM_ANDAMENTO
    assert await contagens(sessao) == antes


async def test_senha_errada_responde_401_e_nada_apagado(cliente, sessao):
    dona = await autenticar(cliente, DONA)
    await semear_analise(sessao, DONA)
    antes = await contagens(sessao)

    resposta = await excluir(cliente, dona, senha="senha-errada-123")

    assert resposta.status_code == 401
    assert await contagens(sessao) == antes


async def test_senha_errada_conta_no_mesmo_bloqueio_do_login(cliente, sessao):
    dona = await autenticar(cliente, DONA)

    for _ in range(MAX_TENTATIVAS):
        assert (await excluir(cliente, dona, senha="senha-errada-123")).status_code == 401
    # Bloqueado: nem a senha certa passa, aqui nem no login.
    assert (await excluir(cliente, dona)).status_code == 429
    login = await cliente.post("/api/v1/auth/login", json={"email": DONA, "senha": SENHA})
    assert login.status_code == 429
    assert await usuario_por_email(sessao, DONA) is not None


async def test_conta_excluida_derruba_access_e_refresh(cliente, sessao):
    await autenticar(cliente, DONA)
    login = await cliente.post("/api/v1/auth/login", json={"email": DONA, "senha": SENHA})
    tokens = login.json()
    cabecalho = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert (await excluir(cliente, cabecalho)).status_code == 204

    assert (await cliente.get("/api/v1/auth/eu", headers=cabecalho)).status_code == 401
    refresh = await cliente.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh.status_code == 401
    assert (await contagens(sessao))["tokens_atualizacao"] == 0
    # As tentativas de login do e-mail também saem (são do e-mail, pseudonimizado).
    sessao.expire_all()
    tentativas = await sessao.scalar(
        select(func.count())
        .select_from(TentativaLogin)
        .where(TentativaLogin.email_hash == hash_token(DONA))
    )
    assert tentativas == 0


async def test_exclusao_registra_evento_sem_email(cliente, caplog):
    dona = await autenticar(cliente, DONA)

    with caplog.at_level(logging.INFO, logger="app.services.conta"):
        assert (await excluir(cliente, dona)).status_code == 204

    linhas = [r.getMessage() for r in caplog.records if "conta_excluida" in r.getMessage()]
    assert len(linhas) == 1
    assert "apagou_empresa=true" in linhas[0]
    assert "id_empresa=" in linhas[0]
    assert DONA not in caplog.text
