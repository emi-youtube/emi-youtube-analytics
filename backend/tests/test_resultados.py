"""Testes das rotas de resultado: agregação, filtros, paginação e portão de dono.

Dados sintéticos, SQLite em memória. O ponto destes testes não é "o endpoint
responde 200" — é que as CONTAS estão certas e que a execução de outro usuário
responde 404, que é a parte que erra em silêncio.

Um teste exercita também as consultas de TEMAS, populando TEMAS e
COMENTARIO_TEMA à mão: o worker de tópicos não existe, mas as consultas existem,
e sem isso elas só seriam descobertas quebradas quando ele chegasse.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.security import hash_token
from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.comentario_tema import ComentarioTema
from app.models.execucao import Execucao
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video
from tests.conftest import autenticar

VIDEO_A = "video-a"
VIDEO_B = "video-b"

# Proveniência como o classificador léxico grava: sem `f1_macro`, porque ele
# nunca foi avaliado contra o gabarito humano (CLAUDE.md regra 6).
PROVENIENCIA_LEXICO = {
    "proveniencia": {
        "metodo": "soma de polaridade sobre o SentiLex-PT02",
        "recurso": {"nome": "SentiLex-PT02", "sha256": "88ab7389"},
    }
}


# --------------------------------------------------------------------------- cenário


async def montar_cenario(
    cliente,
    sessao,
    *,
    email: str,
    nome_modelo: str = "Campanha de verão",
    status: str = "concluida",
    metricas: dict | None = None,
    textos_por_sentimento: dict[str, list[str]] | None = None,
    com_temas: bool = False,
) -> dict:
    """Usuário -> modelo -> execução concluída -> 2 vídeos -> comentários analisados.

    O usuário é criado pela API (`autenticar` registra e loga), e não inserido à
    mão: a senha tem de casar com o hash que o login confere, e um `senha_hash`
    fabricado aqui daria 401 em todo teste. Devolve o cabeçalho pronto.

    `textos_por_sentimento` controla quantos comentários de cada rótulo existem e
    o texto de cada um (o comprimento importa: é o critério do representativo).
    """
    cabecalho = await autenticar(cliente, email)
    usuario = await sessao.scalar(select(Usuario).where(Usuario.email == email))
    assert usuario is not None, "autenticar deveria ter registrado o usuario"

    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario,
        nome=nome_modelo,
        termo_pesquisa="tênis",
        filtros={"videos": [VIDEO_A, VIDEO_B]},
    )
    sessao.add(modelo)
    await sessao.flush()

    execucao = Execucao(
        id_modelo=modelo.id_modelo,
        status=status,
        iniciado_em=datetime(2026, 9, 24, 10, 0, tzinfo=UTC),
        concluido_em=datetime(2026, 9, 24, 10, 5, tzinfo=UTC) if status == "concluida" else None,
    )
    sessao.add(execucao)
    await sessao.flush()

    video_a = Video(
        id_execucao=execucao.id_execucao,
        youtube_video_id=VIDEO_A,
        titulo="Anúncio A",
        canal="Loja Exemplo",
        visualizacoes=10_000,
        curtidas=500,
    )
    video_b = Video(
        id_execucao=execucao.id_execucao,
        youtube_video_id=VIDEO_B,
        titulo="Anúncio B",
        canal="Loja Exemplo",
        visualizacoes=5_000,
        curtidas=100,
    )
    sessao.add_all([video_a, video_b])
    await sessao.flush()

    # Reaproveita a linha de versão se ela já existe, como `garantir_versao` faz
    # em produção: `uq_versoes_modelo_nome_versao` (migration 0008) proíbe a
    # segunda, e um cenário com dois usuários criaria duas.
    versao = await sessao.scalar(
        select(VersaoModelo).where(
            VersaoModelo.nome_modelo == "lexico-sentilex", VersaoModelo.versao == "1.0.0"
        )
    )
    if versao is None:
        versao = VersaoModelo(
            nome_modelo="lexico-sentilex",
            versao="1.0.0",
            metricas_avaliacao=metricas if metricas is not None else PROVENIENCIA_LEXICO,
            status="ativo",
        )
        sessao.add(versao)
    elif metricas is not None:
        versao.metricas_avaliacao = metricas
    await sessao.flush()

    textos = textos_por_sentimento or {
        "positivo": ["adorei", "muito bom mesmo", "o melhor de todos que eu ja vi"],
        "negativo": ["ruim", "detestei bastante"],
        "neutro": ["ok"],
    }

    criados: list[Comentario] = []
    indice = 0
    for sentimento, lista in textos.items():
        for texto in lista:
            # Alterna os vídeos para o corte por vídeo ter o que filtrar.
            video = video_a if indice % 2 == 0 else video_b
            comentario = Comentario(
                id_video=video.id_video,
                youtube_comment_id=f"c{indice}",
                autor_hash=hash_token(f"autor{indice}"),
                texto=texto,
            )
            sessao.add(comentario)
            await sessao.flush()
            sessao.add(
                AnaliseSentimento(
                    id_comentario=comentario.id_comentario,
                    id_versao_modelo=versao.id_versao,
                    sentimento=sentimento,
                    justificativa=f"justificativa de {texto[:12]}",
                    processado_em=datetime(2026, 9, 24, 10, 4, tzinfo=UTC),
                )
            )
            criados.append(comentario)
            indice += 1

    tema = None
    if com_temas:
        tema = Tema(
            id_execucao=execucao.id_execucao,
            rotulo_tema="preço",
            palavras_chave=["caro", "preco"],
        )
        sessao.add(tema)
        await sessao.flush()
        for comentario in criados[:2]:
            sessao.add(
                ComentarioTema(
                    id_comentario=comentario.id_comentario, id_tema=tema.id_tema, peso=0.9
                )
            )

    await sessao.commit()
    return {
        "cabecalho": cabecalho,
        "usuario": usuario,
        "modelo": modelo,
        "execucao": execucao,
        "videos": {VIDEO_A: video_a, VIDEO_B: video_b},
        "versao": versao,
        "comentarios": criados,
        "tema": tema,
    }


# --------------------------------------------------------------------------- GET /resultado


async def test_resultado_agrega_a_distribuicao(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="d1@exemplo.com")
    cabecalho = dados["cabecalho"]

    resposta = await cliente.get(
        f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["distribuicao"] == {"positivo": 3, "neutro": 1, "negativo": 2, "total": 6}
    assert corpo["nome_modelo_analise"] == "Campanha de verão"


async def test_resultado_soma_o_alcance_e_a_taxa_por_mil_views(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="d2@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    alcance = corpo["alcance"]
    assert alcance["visualizacoes"] == 15_000
    assert alcance["curtidas"] == 600
    assert alcance["comentarios"] == 6
    # 6 comentários / (15000/1000) = 0,4
    assert alcance["comentarios_por_mil_views"] == pytest.approx(0.4)


async def test_resultado_quebra_por_video(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="d3@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    assert len(corpo["videos"]) == 2
    por_id = {v["video"]["youtube_video_id"]: v for v in corpo["videos"]}
    # 6 comentários alternando entre os dois vídeos: 3 em cada.
    assert por_id[VIDEO_A]["distribuicao"]["total"] == 3
    assert por_id[VIDEO_B]["distribuicao"]["total"] == 3
    assert sum(v["distribuicao"]["total"] for v in corpo["videos"]) == 6


async def test_resultado_traz_temas_vazios_sem_worker_de_topicos(cliente, sessao):
    """Sem worker de tópicos, TEMAS não tem linha — e isso é lista vazia, não erro."""
    dados = await montar_cenario(cliente, sessao, email="d4@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    assert corpo["temas"] == []
    assert corpo["ponto_de_atencao"] is None
    assert all(item["temas"] == [] for item in corpo["comentarios_representativos"])


async def test_consultas_de_tema_funcionam_quando_ha_tema(cliente, sessao):
    """As consultas de tema já estão escritas: acendem sozinhas com o worker.

    Popula TEMAS e COMENTARIO_TEMA à mão para provar isso agora, em vez de
    descobrir a consulta quebrada quando o worker de tópicos chegar.
    """
    dados = await montar_cenario(cliente, sessao, email="d5@exemplo.com", com_temas=True)
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    assert len(corpo["temas"]) == 1
    tema = corpo["temas"][0]
    assert tema["tema"]["rotulo_tema"] == "preço"
    assert tema["tema"]["palavras_chave"] == ["caro", "preco"]
    # Dois comentários ligados ao tema.
    assert tema["distribuicao"]["total"] == 2


async def test_representativos_usam_a_mediana_de_comprimento(cliente, sessao):
    """Critério determinístico e explicado: nem o mais longo nem o mais curto.

    Positivos com 3, 15 e 30 caracteres -> escolhe o do meio. O mais longo é
    quase sempre desabafo atípico; o mais curto é "kkkk".
    """
    dados = await montar_cenario(
        cliente,
        sessao,
        email="d6@exemplo.com",
        textos_por_sentimento={
            "positivo": ["bom", "gostei bastante!", "esse aqui e o melhor anuncio ja"],
            "negativo": ["pessimo"],
            "neutro": ["sei la"],
        },
    )
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    escolhidos = {
        item["analise"]["sentimento"]: item["comentario"]["texto"]
        for item in corpo["comentarios_representativos"]
    }
    assert escolhidos["positivo"] == "gostei bastante!"
    assert escolhidos["negativo"] == "pessimo"
    assert escolhidos["neutro"] == "sei la"
    # Um por sentimento, na ordem positivo -> neutro -> negativo.
    assert [i["analise"]["sentimento"] for i in corpo["comentarios_representativos"]] == [
        "positivo",
        "neutro",
        "negativo",
    ]


async def test_representativos_cobrem_sentimento_com_contagem_par(cliente, sessao):
    """Regressão: contagem PAR tem de devolver representativo como a ímpar.

    `(total + 1) / 2` no SQLAlchemy 2.0 é divisão REAL — 6 comentários davam
    3.5, que não casa com nenhum `row_number`, e o sentimento desaparecia da
    amostra sem erro nenhum. Os testes anteriores usavam só contagens ímpares e
    passavam; o bug apareceu na execução real (neutro 30, negativo 6).
    """
    dados = await montar_cenario(
        cliente,
        sessao,
        email="par@exemplo.com",
        textos_por_sentimento={
            "positivo": ["bom", "muito bom mesmo"],  # 2 -> par
            "negativo": ["ruim", "pessimo demais", "horrivel isso ai", "detestei"],  # 4 -> par
            "neutro": ["ok", "sei la", "tanto faz", "indiferente", "normal", "meio"],  # 6 -> par
        },
    )
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    sentimentos = [i["analise"]["sentimento"] for i in corpo["comentarios_representativos"]]
    assert sentimentos == ["positivo", "neutro", "negativo"]
    # Mediana BAIXA: com 2 positivos ordenados por comprimento, é o mais curto.
    escolhidos = {
        i["analise"]["sentimento"]: i["comentario"]["texto"]
        for i in corpo["comentarios_representativos"]
    }
    assert escolhidos["positivo"] == "bom"


async def test_um_representativo_por_sentimento_presente(cliente, sessao):
    """Exatamente um por sentimento que existe — nunca dois, nunca zero."""
    dados = await montar_cenario(cliente, sessao, email="umpor@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    sentimentos = [i["analise"]["sentimento"] for i in corpo["comentarios_representativos"]]
    # O cenário padrão tem positivo 3, neutro 1, negativo 2 (um par).
    assert sorted(sentimentos) == ["negativo", "neutro", "positivo"]


async def test_representativos_sao_estaveis_entre_chamadas(cliente, sessao):
    """Nada de aleatório: a mesma execução devolve sempre o mesmo comentário."""
    dados = await montar_cenario(cliente, sessao, email="d7@exemplo.com")
    cabecalho = dados["cabecalho"]
    url = f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado"

    primeira = (await cliente.get(url, headers=cabecalho)).json()
    segunda = (await cliente.get(url, headers=cabecalho)).json()

    ids = lambda c: [i["comentario"]["id_comentario"] for i in c["comentarios_representativos"]]  # noqa: E731
    assert ids(primeira) == ids(segunda)


async def test_versao_do_modelo_vem_da_analise_e_sem_metrica(cliente, sessao):
    """O léxico não tem F1: `metricas_avaliacao` é nulo, e a tela tem que aguentar."""
    dados = await montar_cenario(cliente, sessao, email="d8@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    versao = corpo["versao_modelo"]
    assert versao["nome_modelo"] == "lexico-sentilex"
    assert versao["versao"] == "1.0.0"
    # Proveniência não é avaliação — nulo, não `{}` nem o dicionário cru.
    assert versao["metricas_avaliacao"] is None
    assert versao["em_uso_desde"] is not None


async def test_versao_com_f1_registrado_devolve_as_metricas(cliente, sessao):
    """Quando o BERTimbau avaliado entrar, o mesmo campo passa a vir preenchido."""
    dados = await montar_cenario(
        cliente,
        sessao,
        email="d9@exemplo.com",
        metricas={"f1_macro": 0.81, "acuracia": 0.83, "exemplos_teste": 334},
    )
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    assert corpo["versao_modelo"]["metricas_avaliacao"]["f1_macro"] == pytest.approx(0.81)


async def test_confianca_vem_nula_porque_a_coluna_nao_existe(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="d10@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    assert all(i["analise"]["confianca"] is None for i in corpo["comentarios_representativos"])


async def test_insights_da_campanha_vazios_na_primeira_coleta(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="d11@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
        )
    ).json()

    assert corpo["insights_da_campanha"] == []
    # Amostra pequena não produz insight de execução — e isso é o normal.
    assert isinstance(corpo["insights"], list)


# --------------------------------------------------------------------------- dono


async def test_resultado_de_outro_usuario_responde_404(cliente, sessao):
    """404 e não 403: um 403 confirmaria que aquele id existe."""
    dados = await montar_cenario(cliente, sessao, email="dona@exemplo.com")
    cabecalho_intruso = await autenticar(cliente, "intruso@exemplo.com")

    for caminho in ("resultado", "comentarios"):
        resposta = await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/{caminho}",
            headers=cabecalho_intruso,
        )
        assert resposta.status_code == 404, caminho


async def test_lista_de_resultados_so_traz_as_do_usuario(cliente, sessao):
    minha = await montar_cenario(cliente, sessao, email="minha@exemplo.com", nome_modelo="Minha")
    await montar_cenario(cliente, sessao, email="outra@exemplo.com", nome_modelo="Outra")
    cabecalho = minha["cabecalho"]

    corpo = (await cliente.get("/api/v1/execucoes/resultados", headers=cabecalho)).json()

    assert [item["id_execucao"] for item in corpo] == [minha["execucao"].id_execucao]
    assert corpo[0]["nome_modelo_analise"] == "Minha"
    assert corpo[0]["distribuicao"]["total"] == 6
    assert corpo[0]["total_videos"] == 2
    assert corpo[0]["total_temas"] == 0


async def test_rota_resultados_nao_e_confundida_com_id(cliente, sessao):
    """`/execucoes/resultados` tem de bater na rota literal, não em `/{id:int}`."""
    cabecalho = (await montar_cenario(cliente, sessao, email="ordem@exemplo.com"))["cabecalho"]

    resposta = await cliente.get("/api/v1/execucoes/resultados", headers=cabecalho)

    assert resposta.status_code == 200
    assert isinstance(resposta.json(), list)


async def test_execucao_nao_concluida_fica_fora_da_lista(cliente, sessao):
    cabecalho = (
        await montar_cenario(cliente, sessao, email="andando@exemplo.com", status="processando")
    )["cabecalho"]

    corpo = (await cliente.get("/api/v1/execucoes/resultados", headers=cabecalho)).json()

    assert corpo == []


# --------------------------------------------------------------------------- comentários


async def test_comentarios_paginam(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="p1@exemplo.com")
    cabecalho = dados["cabecalho"]
    url = f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios"

    primeira = (await cliente.get(f"{url}?pagina=1&tamanho=4", headers=cabecalho)).json()
    segunda = (await cliente.get(f"{url}?pagina=2&tamanho=4", headers=cabecalho)).json()

    assert primeira["total"] == 6
    assert len(primeira["itens"]) == 4
    assert len(segunda["itens"]) == 2
    # Sem sobreposição entre as páginas.
    ids_primeira = {i["comentario"]["id_comentario"] for i in primeira["itens"]}
    ids_segunda = {i["comentario"]["id_comentario"] for i in segunda["itens"]}
    assert not (ids_primeira & ids_segunda)


async def test_filtro_por_sentimento(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="p2@exemplo.com")
    cabecalho = dados["cabecalho"]
    url = f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios"

    corpo = (
        await cliente.get(f"{url}?pagina=1&tamanho=50&sentimento=negativo", headers=cabecalho)
    ).json()

    assert corpo["total"] == 2
    assert all(i["analise"]["sentimento"] == "negativo" for i in corpo["itens"])


async def test_contagem_por_sentimento_ignora_o_filtro_de_sentimento(cliente, sessao):
    """Os chips "Positivo · 3 / Neutro · 1" continuam visíveis depois do clique."""
    dados = await montar_cenario(cliente, sessao, email="p3@exemplo.com")
    cabecalho = dados["cabecalho"]
    url = f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios"

    corpo = (
        await cliente.get(f"{url}?pagina=1&tamanho=50&sentimento=negativo", headers=cabecalho)
    ).json()

    assert corpo["total"] == 2  # o filtro vale para a lista
    assert corpo["contagem_por_sentimento"] == {
        "positivo": 3,
        "neutro": 1,
        "negativo": 2,
        "total": 6,
    }


async def test_filtro_por_video(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="p4@exemplo.com")
    cabecalho = dados["cabecalho"]
    id_video = dados["videos"][VIDEO_B].id_video
    url = f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios"

    corpo = (
        await cliente.get(f"{url}?pagina=1&tamanho=50&id_video={id_video}", headers=cabecalho)
    ).json()

    assert corpo["total"] == 3
    assert all(i["video"]["youtube_video_id"] == VIDEO_B for i in corpo["itens"])


async def test_busca_textual(cliente, sessao):
    dados = await montar_cenario(
        cliente,
        sessao,
        email="p5@exemplo.com",
        textos_por_sentimento={
            "positivo": ["adorei o tenis", "produto otimo"],
            "negativo": ["odiei o tenis"],
            "neutro": ["sem opiniao"],
        },
    )
    cabecalho = dados["cabecalho"]
    url = f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios"

    corpo = (await cliente.get(f"{url}?pagina=1&tamanho=50&busca=tenis", headers=cabecalho)).json()

    assert corpo["total"] == 2
    assert all("tenis" in i["comentario"]["texto"] for i in corpo["itens"])


async def test_busca_escapa_curinga_do_like(cliente, sessao):
    """Buscar "100%" não pode casar com a execução inteira."""
    dados = await montar_cenario(
        cliente,
        sessao,
        email="p6@exemplo.com",
        textos_por_sentimento={
            "positivo": ["desconto de 100% mesmo"],
            "negativo": ["nao gostei nada"],
            "neutro": ["indiferente"],
        },
    )
    cabecalho = dados["cabecalho"]
    url = f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios"

    corpo = (await cliente.get(f"{url}?pagina=1&tamanho=50&busca=100%25", headers=cabecalho)).json()

    assert corpo["total"] == 1
    assert "100%" in corpo["itens"][0]["comentario"]["texto"]


async def test_filtro_por_tema(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="p7@exemplo.com", com_temas=True)
    cabecalho = dados["cabecalho"]
    url = f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios"

    corpo = (
        await cliente.get(
            f"{url}?pagina=1&tamanho=50&id_tema={dados['tema'].id_tema}", headers=cabecalho
        )
    ).json()

    assert corpo["total"] == 2
    assert all(i["temas"][0]["rotulo_tema"] == "preço" for i in corpo["itens"])


async def test_sentimento_invalido_responde_422(cliente, sessao):
    """Valor fora do CHECK é erro, não página vazia — que pareceria "sem resultado"."""
    dados = await montar_cenario(cliente, sessao, email="p8@exemplo.com")
    cabecalho = dados["cabecalho"]

    resposta = await cliente.get(
        f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios"
        "?pagina=1&tamanho=5&sentimento=POSITIVO",
        headers=cabecalho,
    )

    assert resposta.status_code == 422


async def test_comentario_nao_expoe_autor_original(cliente, sessao):
    """LGPD (CLAUDE.md regra 2): só o hash existe, e o hash não é o autor."""
    dados = await montar_cenario(cliente, sessao, email="p9@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (
        await cliente.get(
            f"/api/v1/execucoes/{dados['execucao'].id_execucao}/comentarios?pagina=1&tamanho=5",
            headers=cabecalho,
        )
    ).json()

    for item in corpo["itens"]:
        autor_hash = item["comentario"]["autor_hash"]
        assert len(autor_hash) == 64  # SHA-256 em hex
        assert "@" not in autor_hash


# --------------------------------------------------------------------------- painel


async def test_painel_resume_a_ultima_execucao_concluida(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="pa1@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (await cliente.get("/api/v1/painel", headers=cabecalho)).json()

    destaque = corpo["destaque"]
    assert destaque["id_execucao"] == dados["execucao"].id_execucao
    assert destaque["nome_modelo_analise"] == "Campanha de verão"
    assert destaque["total_comentarios"] == 6
    assert destaque["total_videos"] == 2
    assert destaque["total_temas"] == 0
    assert destaque["distribuicao"]["positivo"] == 3


async def test_painel_lista_os_modelos_com_a_ultima_execucao(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="pa2@exemplo.com")
    cabecalho = dados["cabecalho"]

    corpo = (await cliente.get("/api/v1/painel", headers=cabecalho)).json()

    assert len(corpo["modelos"]) == 1
    linha = corpo["modelos"][0]
    assert linha["nome"] == "Campanha de verão"
    # Vem de filtros.videos: VIDEOS só existe depois da coleta.
    assert linha["total_videos"] == 2
    assert linha["status_ultima_execucao"] == "concluida"
    assert linha["id_execucao_concluida"] == dados["execucao"].id_execucao
    assert linha["motivo_da_falha"] is None


async def test_painel_totais_e_cota(cliente, sessao):
    cabecalho = (await montar_cenario(cliente, sessao, email="pa3@exemplo.com"))["cabecalho"]

    corpo = (await cliente.get("/api/v1/painel", headers=cabecalho)).json()

    assert corpo["totais"] == {
        "comentarios_analisados": 6,
        "execucoes_concluidas": 1,
        "videos_acompanhados": 2,
    }
    # Ninguém registra consumo de cota ainda: nulo, não número inventado.
    assert corpo["cota_youtube"] is None
    assert corpo["versao_modelo"]["nome_modelo"] == "lexico-sentilex"
    assert corpo["versao_modelo"]["metricas_avaliacao"] is None


async def test_painel_de_conta_nova_nao_quebra(cliente):
    """Conta sem execução nenhuma: painel vazio, não 404 nem 500."""
    cabecalho = await autenticar(cliente, "nova@exemplo.com")

    resposta = await cliente.get("/api/v1/painel", headers=cabecalho)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["destaque"] is None
    assert corpo["modelos"] == []
    assert corpo["totais"]["comentarios_analisados"] == 0
    assert corpo["versao_modelo"] is None


async def test_painel_nao_soma_dado_de_outro_usuario(cliente, sessao):
    meu = await montar_cenario(cliente, sessao, email="meu@exemplo.com")
    await montar_cenario(cliente, sessao, email="alheio@exemplo.com")
    cabecalho = meu["cabecalho"]

    corpo = (await cliente.get("/api/v1/painel", headers=cabecalho)).json()

    # 6 e não 12: o painel é do dono, não do banco.
    assert corpo["totais"]["comentarios_analisados"] == 6
    assert corpo["totais"]["execucoes_concluidas"] == 1
    assert len(corpo["modelos"]) == 1


async def test_painel_mostra_o_motivo_da_falha(cliente, sessao):
    """Execução que morreu na DLQ: a linha do modelo diz por quê."""
    from app.models.job_dlq import JobDlq

    dados = await montar_cenario(cliente, sessao, email="pa6@exemplo.com", status="erro")
    sessao.add(
        JobDlq(
            id_job=999,
            tipo="coleta",
            id_execucao=dados["execucao"].id_execucao,
            erro="Nenhum ID de video no filtro do modelo",
        )
    )
    await sessao.commit()
    cabecalho = dados["cabecalho"]

    corpo = (await cliente.get("/api/v1/painel", headers=cabecalho)).json()

    linha = corpo["modelos"][0]
    assert linha["status_ultima_execucao"] == "erro"
    assert "Nenhum ID de video" in linha["motivo_da_falha"]
    assert linha["id_execucao_concluida"] is None
    assert corpo["destaque"] is None


# --------------------------------------------------------------------------- sem autenticação


async def test_rotas_de_resultado_exigem_token(cliente, sessao):
    dados = await montar_cenario(cliente, sessao, email="pa7@exemplo.com")
    id_execucao = dados["execucao"].id_execucao

    for caminho in (
        "/api/v1/painel",
        "/api/v1/execucoes/resultados",
        f"/api/v1/execucoes/{id_execucao}/resultado",
        f"/api/v1/execucoes/{id_execucao}/comentarios?pagina=1&tamanho=5",
    ):
        resposta = await cliente.get(caminho)
        assert resposta.status_code in (401, 403), caminho


# --------------------------------------------------------------------------- agregação no SQL


async def test_agregacao_nao_carrega_comentarios_para_a_memoria(cliente, sessao, monkeypatch):
    """Guarda-corpo do CLAUDE.md: contagem é GROUP BY, não laço em Python.

    Conta as linhas de COMENTARIOS que a sessão materializa ao montar o
    resultado. Com laço em Python seriam todas; com GROUP BY são só as dos
    representativos (no máximo três).
    """
    dados = await montar_cenario(cliente, sessao, email="sql@exemplo.com")
    cabecalho = dados["cabecalho"]

    materializados: list[int] = []
    original = Comentario.__init__

    # Instrumenta a construção de instâncias ORM de Comentario.
    def contar(self, *args, **kwargs):
        materializados.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Comentario, "__init__", contar)

    await cliente.get(
        f"/api/v1/execucoes/{dados['execucao'].id_execucao}/resultado", headers=cabecalho
    )

    # Os 6 comentários existem; o resultado traz 3 representativos.
    total = await sessao.scalar(select(Comentario.id_comentario).limit(1))
    assert total is not None
    assert len(materializados) <= 3, (
        f"{len(materializados)} comentarios materializados: a agregacao vazou para o Python"
    )
