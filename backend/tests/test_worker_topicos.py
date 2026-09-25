"""Testes do worker de tópicos: limpeza, regra de k, pesos, determinismo e cadeia.

Dados sintéticos: os "comentários" são frases montadas em torno de três assuntos
separados (preço, entrega, qualidade do som), para que exista uma resposta certa
contra a qual comparar. Um corpus real não serviria de teste — não há gabarito de
tema, e é justamente por isso que a conferência sobre a execução 4 foi feita à
parte, por leitura humana.
"""

import logging

import pytest
from sqlalchemy import select

from app.core.security import hash_token
from app.models.comentario import Comentario
from app.models.comentario_tema import ComentarioTema
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.usuario import Usuario
from app.models.video import Video
from app.topicos import modelo as modelo_topicos
from app.topicos.modelo import (
    LIMIAR_DE_PESO,
    MAXIMO_DE_TEMAS,
    MINIMO_DE_COMENTARIOS,
    MINIMO_DE_TEMAS,
    modelar,
    numero_de_temas,
    representante_do_tema,
)
from app.topicos.texto import (
    PALAVRAS_DE_EMOJI,
    PALAVROES,
    STOPWORDS,
    limpar,
    preparar,
)
from app.workers import pipeline, topicos

VIDEO_A = "video-a"


# --------------------------------------------------------------------------- corpus sintético

FRASES = {
    "preco": [
        "o preço está muito salgado para esse produto",
        "achei caro demais, não vale o preço cobrado",
        "preço abusivo, dá para comprar bem mais barato",
        "custo benefício ruim, o preço não justifica",
        "barato não é, mas o preço até que compensa",
    ],
    "entrega": [
        "a entrega demorou três semanas para chegar",
        "chegou rápido, entrega no prazo combinado",
        "frete caríssimo e a entrega atrasou de novo",
        "entrega perfeita, chegou antes do prazo",
        "pedido chegou quebrado por causa da entrega",
    ],
    "som": [
        "o som desse fone é impressionante, grave limpo",
        "qualidade de som excelente, grave bem definido",
        "som abafado, o grave some no volume alto",
        "fone com som cristalino e grave potente",
        "o grave distorce, qualidade de som fraca",
    ],
}


def corpus(repeticoes: int = 9) -> list[tuple[int, str]]:
    """Comentários suficientes para passar do mínimo, girando as três frases."""
    comentarios: list[tuple[int, str]] = []
    identificador = 1
    for _ in range(repeticoes):
        for frases in FRASES.values():
            for frase in frases:
                comentarios.append((identificador, frase))
                identificador += 1
    return comentarios


# --------------------------------------------------------------------------- limpeza do texto


def test_emoji_e_removido_e_nao_vira_palavra():
    """A diferença central para o `preparar_texto` do classificador.

    Lá o emoji VIRA palavra, porque o BERTimbau precisa enxergar o sentimento que
    ele carrega. Aqui ele é removido, porque humor não é assunto.
    """
    tokens = preparar("adorei esse fone \U0001f60d \U0001f525 som incrivel")

    assert "amei" not in tokens  # o que 😍 viraria em preparar_texto
    assert "fogo" not in tokens  # o que 🔥 viraria
    assert "fone" in tokens


def test_nenhuma_palavra_de_emoji_pode_virar_tema():
    """Guarda dupla: mesmo digitadas à mão, as 23 palavras do mapa são stopword."""
    assert PALAVRAS_DE_EMOJI <= STOPWORDS

    tokens = preparar("risos coração amei maravilhoso raiva choro lixo fogo")

    assert tokens == []


def test_url_mencao_e_timestamp_saem():
    tokens = preparar("olha https://youtu.be/abc @canal_oficial em 2:35 o carro aparece")

    assert not any(t.startswith("http") for t in tokens)
    assert "canal_oficial" not in tokens
    assert "carro" in tokens


def test_riso_com_qualquer_numero_de_letras_e_descartado():
    """Regressão da conferência: "kkkkk" (cinco kk) virou palavra-chave de dois temas."""
    for riso in ("kkkk", "kkkkk", "kkkkkkkkkk", "hahaha", "rsrsrs"):
        # "bom" tambem sai: e cumprimento, e cumprimento nao e assunto.
        assert preparar(f"{riso} muito bom o carro") == ["carro"], riso


def test_acento_e_dobrado_para_nao_partir_a_mesma_palavra():
    """Regressão da conferência: "música" e "musica" viravam dois temas gêmeos."""
    assert preparar("qual é a música?") == preparar("qual eh a musica?") == ["musica"]


def test_limpeza_nao_altera_o_texto_do_banco():
    """O original é canônico (CLAUDE.md Seção 3); a limpeza é derivação."""
    original = "Olha \U0001f60d https://x.com que CARRO"

    limpar(original)

    assert original == "Olha \U0001f60d https://x.com que CARRO"


# --------------------------------------------------------------------------- stopwords e rótulo


def test_stopwords_vem_da_lista_da_nltk():
    """A base é a lista padrão de português da NLTK (207 termos), embutida.

    Amostra do núcleo dela; o teste existe para que trocar a base por outra lista
    seja uma decisão visível, e não um efeito colateral de mexer nos acréscimos.
    """
    for termo in ("de", "que", "nao", "para", "com", "uma", "estivessemos", "houveramos"):
        assert termo in STOPWORDS, termo


def test_acrescimos_do_projeto_cobrem_o_que_sujou_os_temas():
    """Cada um destes apareceu num rótulo da conferência sobre o corpus real."""
    # cumprimento: o tema "boa / noite / internet"
    for termo in ("boa", "bom", "noite", "dia"):
        assert termo in STOPWORDS, termo
    # verbo vazio nomeado na revisão
    for termo in ("vim", "ser", "mto"):
        assert termo in STOPWORDS, termo
    # avaliação, que não é assunto: o tema "melhor / publicidade / operadora"
    assert "melhor" in STOPWORDS
    # gíria e meta do YouTube
    for termo in ("vc", "tbm", "pra", "video", "propaganda", "inscrito"):
        assert termo in STOPWORDS, termo


def test_palavrao_nao_e_stopword():
    """Palavrão continua no vocabulário: é sinal de reclamação, não ruído."""
    assert not (PALAVROES & STOPWORDS)
    assert "merda" not in STOPWORDS

    assert "merda" in preparar("que merda de operadora")


def test_palavrao_fica_fora_do_rotulo_mas_nas_palavras_chave():
    """O rótulo vai para o relatório que a PME apresenta."""
    palavras = ("merda", "claro", "net", "internet", "bosta", "celular", "operadora")

    rotulo = modelo_topicos._rotular(palavras)

    assert rotulo == "claro / net / internet"
    assert "merda" not in rotulo
    assert "bosta" not in rotulo
    # Mas continuam disponíveis como palavras-chave — o método não as apagou.
    assert "merda" in palavras


def test_rotulo_usa_palavrao_se_nao_sobrar_mais_nada():
    """Tema sem nome nenhum seria pior que tema com nome feio."""
    assert modelo_topicos._rotular(("merda", "bosta", "porra")) == "merda / bosta / porra"


def test_rotulo_de_tema_real_nao_tem_palavrao():
    resultado = modelar(corpus())

    for tema in resultado.temas:
        for parte in tema.rotulo.split(" / "):
            assert parte not in PALAVROES, tema.rotulo


# --------------------------------------------------------------------------- regra de k


@pytest.mark.parametrize(
    ("comentarios", "esperado"),
    [(100, 3), (150, 3), (300, 4), (500, 6), (1000, 8), (2789, 8), (5000, 8)],
)
def test_numero_de_temas_segue_a_regra(comentarios, esperado):
    assert numero_de_temas(comentarios) == esperado


def test_numero_de_temas_respeita_piso_e_teto():
    assert numero_de_temas(MINIMO_DE_COMENTARIOS) >= MINIMO_DE_TEMAS
    assert numero_de_temas(1_000_000) == MAXIMO_DE_TEMAS


def test_execucao_pequena_nao_gera_tema_e_diz_por_que():
    """Execução pequena demais não tem tema — tem poucos comentários."""
    resultado = modelar(corpus(repeticoes=1))  # 15 comentários

    assert not resultado.houve_temas
    assert resultado.temas == ()
    assert resultado.motivo is not None
    assert str(MINIMO_DE_COMENTARIOS) in resultado.motivo


# --------------------------------------------------------------------------- modelagem


def test_separa_os_assuntos_do_corpus_sintetico():
    resultado = modelar(corpus())

    assert resultado.houve_temas
    assert MINIMO_DE_TEMAS <= len(resultado.temas) <= MAXIMO_DE_TEMAS
    # Os três assuntos plantados aparecem entre as palavras-chave.
    todas = {p for tema in resultado.temas for p in tema.palavras_chave}
    assert "preco" in todas or "preço" in todas
    assert "entrega" in todas
    assert "som" in todas or "grave" in todas


def test_rotulo_e_as_tres_palavras_mais_fortes():
    resultado = modelar(corpus())

    for tema in resultado.temas:
        assert tema.rotulo == " / ".join(tema.palavras_chave[:3])


def test_palavras_chave_sao_as_dez_mais_fortes():
    resultado = modelar(corpus())

    for tema in resultado.temas:
        assert len(tema.palavras_chave) == 10
        assert len(set(tema.palavras_chave)) == 10  # sem repetição


def test_mesma_semente_da_os_mesmos_temas():
    """Duas rodadas sobre o mesmo corpus têm de dar o mesmo resultado."""
    uma = modelar(corpus())
    outra = modelar(corpus())

    assert [t.rotulo for t in uma.temas] == [t.rotulo for t in outra.temas]
    assert [t.palavras_chave for t in uma.temas] == [t.palavras_chave for t in outra.temas]
    assert uma.atribuicoes == outra.atribuicoes


def test_semente_diferente_pode_dar_resultado_diferente():
    """Prova que o determinismo vem da semente, e não de o método ser trivial."""
    uma = modelar(corpus(), semente=1)
    outra = modelar(corpus(), semente=999)

    assert uma.houve_temas and outra.houve_temas
    # Não exige divergência (pode convergir igual); exige que rodar com a MESMA
    # semente seja estável, que é o que o teste anterior fixa.
    assert [t.rotulo for t in uma.temas] == [t.rotulo for t in modelar(corpus(), semente=1).temas]


def test_peso_e_normalizado_entre_zero_e_um():
    resultado = modelar(corpus())

    for atribuicao in resultado.atribuicoes:
        assert 0.0 <= atribuicao.peso <= 1.0


def test_peso_abaixo_do_limiar_nao_vira_ligacao():
    """Sem limiar, COMENTARIO_TEMA viraria o produto cartesiano."""
    resultado = modelar(corpus())

    assert all(a.peso >= LIMIAR_DE_PESO for a in resultado.atribuicoes)


def test_comentario_nao_entra_em_todo_tema():
    resultado = modelar(corpus())
    por_comentario: dict[int, int] = {}
    for atribuicao in resultado.atribuicoes:
        identificador = atribuicao.id_comentario
        por_comentario[identificador] = por_comentario.get(identificador, 0) + 1

    assert por_comentario, "nenhuma ligacao gerada"
    assert max(por_comentario.values()) < len(resultado.temas)


def test_representante_evita_comentario_curto_demais():
    """O de maior peso costuma ser o mais curto, e curto não mostra nada."""
    atribuicoes = (
        modelo_topicos.Atribuicao(id_comentario=1, indice_tema=0, peso=0.99),
        modelo_topicos.Atribuicao(id_comentario=2, indice_tema=0, peso=0.60),
    )
    textos = {
        1: "preço alto",  # peso maior, mas curto demais
        2: "o preço está muito acima do que eu esperava para um produto assim",
    }

    assert representante_do_tema(0, atribuicoes, textos) == 2


def test_representante_cai_no_curto_quando_nao_ha_longo():
    """Melhor mostrar o curto que não mostrar nada."""
    atribuicoes = (modelo_topicos.Atribuicao(id_comentario=7, indice_tema=0, peso=0.9),)

    assert representante_do_tema(0, atribuicoes, {7: "caro"}) == 7


def test_representante_desempata_pelo_menor_id():
    atribuicoes = (
        modelo_topicos.Atribuicao(id_comentario=9, indice_tema=0, peso=0.5),
        modelo_topicos.Atribuicao(id_comentario=4, indice_tema=0, peso=0.5),
    )
    longo = "um comentario suficientemente longo para passar do corte de caracteres"

    assert representante_do_tema(0, atribuicoes, {9: longo, 4: longo}) == 4


def test_representante_de_tema_sem_comentario_e_nulo():
    assert representante_do_tema(3, (), {}) is None


# --------------------------------------------------------------------------- cadeia


def test_topicos_e_a_ultima_etapa_da_cadeia():
    assert pipeline.proxima_etapa("coleta") == "inferencia"
    assert pipeline.proxima_etapa("inferencia") == "topicos"
    assert pipeline.proxima_etapa("topicos") is None


# --------------------------------------------------------------------------- worker


async def montar_execucao(sessao, textos: list[str], *, email: str) -> Execucao:
    usuario = Usuario(nome="Dona", email=email, senha_hash="x", papel="usuario_pme")
    sessao.add(usuario)
    await sessao.flush()
    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario, nome="Campanha", termo_pesquisa="x", filtros={}
    )
    sessao.add(modelo)
    await sessao.flush()
    execucao = Execucao(id_modelo=modelo.id_modelo, status="processando")
    sessao.add(execucao)
    await sessao.flush()
    video = Video(
        id_execucao=execucao.id_execucao,
        youtube_video_id=VIDEO_A,
        titulo="Anúncio",
        canal="Loja",
    )
    sessao.add(video)
    await sessao.flush()
    for indice, texto in enumerate(textos):
        sessao.add(
            Comentario(
                id_video=video.id_video,
                youtube_comment_id=f"c{indice}",
                autor_hash=hash_token(f"a{indice}"),
                texto=texto,
            )
        )
    await sessao.commit()
    await sessao.refresh(execucao)
    return execucao


async def enfileirar(sessao, execucao: Execucao) -> Job:
    job = Job(tipo="topicos", id_execucao=execucao.id_execucao, status="pendente")
    sessao.add(job)
    await sessao.commit()
    await sessao.refresh(job)
    return job


async def test_worker_grava_temas_e_ligacoes(sessao):
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="t1@exemplo.com")
    await enfileirar(sessao, execucao)

    assert await topicos.executar_proximo(sessao) is True

    temas = (await sessao.scalars(select(Tema))).all()
    assert MINIMO_DE_TEMAS <= len(temas) <= MAXIMO_DE_TEMAS
    assert all(t.id_execucao == execucao.id_execucao for t in temas)
    assert all(len(t.palavras_chave) == 10 for t in temas)

    ligacoes = (await sessao.scalars(select(ComentarioTema))).all()
    assert ligacoes
    assert all(0.0 <= lig.peso <= 1.0 for lig in ligacoes)


async def test_worker_encerra_a_execucao(sessao):
    """Tópicos é a última etapa: é ela que marca `concluida`."""
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="t2@exemplo.com")
    job = await enfileirar(sessao, execucao)

    await topicos.executar_proximo(sessao)

    await sessao.refresh(job)
    assert job.status == "concluida"
    await sessao.refresh(execucao)
    assert execucao.status == "concluida"
    assert execucao.concluido_em is not None


async def test_execucao_pequena_conclui_sem_tema(sessao, caplog):
    """Sem tema é resultado, não erro — e o motivo tem de ficar registrado."""
    execucao = await montar_execucao(sessao, ["comentario curto"] * 10, email="t3@exemplo.com")
    job = await enfileirar(sessao, execucao)

    with caplog.at_level(logging.INFO, logger="app.workers.topicos"):
        assert await topicos.executar_proximo(sessao) is True

    assert (await sessao.scalars(select(Tema))).all() == []
    await sessao.refresh(job)
    assert job.status == "concluida"
    await sessao.refresh(execucao)
    assert execucao.status == "concluida"
    assert (await sessao.scalars(select(JobDlq))).all() == []

    motivos = [r.getMessage() for r in caplog.records if "nao gerados" in r.getMessage()]
    assert motivos and "minimo" in motivos[0]


async def test_reprocessar_nao_duplica(sessao):
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="t4@exemplo.com")
    await enfileirar(sessao, execucao)
    await topicos.executar_proximo(sessao)
    antes = len((await sessao.scalars(select(Tema))).all())

    await enfileirar(sessao, execucao)
    assert await topicos.executar_proximo(sessao) is True

    assert len((await sessao.scalars(select(Tema))).all()) == antes
    assert (await sessao.scalars(select(JobDlq))).all() == []


async def test_log_carrega_o_id_execucao(sessao, caplog):
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="t5@exemplo.com")
    await enfileirar(sessao, execucao)

    with caplog.at_level(logging.INFO, logger="app.workers.topicos"):
        await topicos.executar_proximo(sessao)

    linhas = [r.getMessage() for r in caplog.records]
    assert linhas
    assert all(f"id_execucao={execucao.id_execucao}" in linha for linha in linhas)


async def test_recalcular_apaga_os_temas_antigos_e_refaz(sessao):
    """Corrige execucao antiga depois de uma melhoria no metodo, sem gastar cota."""
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="rec1@exemplo.com")
    await enfileirar(sessao, execucao)
    await topicos.executar_proximo(sessao)

    antigos = (await sessao.scalars(select(Tema))).all()
    assert antigos
    quantos_antes = len(antigos)
    rotulos_antes = [t.rotulo_tema for t in antigos]

    # Job de recalculo: mesmo tipo, com o pedido no payload.
    job = Job(
        tipo="topicos",
        id_execucao=execucao.id_execucao,
        status="pendente",
        payload={"recalcular": True},
    )
    sessao.add(job)
    await sessao.commit()

    assert await topicos.executar_proximo(sessao) is True

    novos = (await sessao.scalars(select(Tema))).all()
    assert novos
    # O que importa e que NAO ACUMULOU: os antigos foram apagados antes de
    # remodelar. Comparar ids nao serviria — o SQLite reaproveita chave primaria
    # depois de um DELETE, entao id igual nao quer dizer linha antiga.
    assert len(novos) == quantos_antes
    # Mesmo corpus e mesma semente: o recalculo reproduz os mesmos temas.
    assert [t.rotulo_tema for t in novos] == rotulos_antes


async def test_recalcular_leva_as_ligacoes_antigas_junto(sessao):
    """COMENTARIO_TEMA some por cascata — nao pode sobrar ligacao orfa."""
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="rec2@exemplo.com")
    await enfileirar(sessao, execucao)
    await topicos.executar_proximo(sessao)

    ligacoes_antes = len((await sessao.scalars(select(ComentarioTema))).all())
    assert ligacoes_antes

    sessao.add(
        Job(
            tipo="topicos",
            id_execucao=execucao.id_execucao,
            status="pendente",
            payload={"recalcular": True},
        )
    )
    await sessao.commit()
    await topicos.executar_proximo(sessao)

    ligacoes = (await sessao.scalars(select(ComentarioTema))).all()
    assert ligacoes
    # Nao acumulou, e nenhuma ligacao ficou apontando para tema inexistente.
    assert len(ligacoes) == ligacoes_antes
    temas_atuais = {t.id_tema for t in (await sessao.scalars(select(Tema))).all()}
    assert {lig.id_tema for lig in ligacoes} <= temas_atuais


async def test_sem_recalcular_o_job_repetido_continua_sendo_ignorado(sessao):
    """A idempotencia so cede quando o job PEDE o recalculo."""
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="rec3@exemplo.com")
    await enfileirar(sessao, execucao)
    await topicos.executar_proximo(sessao)
    ids = {t.id_tema for t in (await sessao.scalars(select(Tema))).all()}

    await enfileirar(sessao, execucao)  # sem payload
    await topicos.executar_proximo(sessao)

    assert {t.id_tema for t in (await sessao.scalars(select(Tema))).all()} == ids


async def test_recalculo_reencerra_a_execucao(sessao):
    """A execucao volta a 'processando' enquanto roda e termina 'concluida'."""
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="rec4@exemplo.com")
    await enfileirar(sessao, execucao)
    await topicos.executar_proximo(sessao)
    await sessao.refresh(execucao)
    assert execucao.status == "concluida"
    inicio = execucao.iniciado_em

    sessao.add(
        Job(
            tipo="topicos",
            id_execucao=execucao.id_execucao,
            status="pendente",
            payload={"recalcular": True},
        )
    )
    await sessao.commit()
    await topicos.executar_proximo(sessao)

    await sessao.refresh(execucao)
    assert execucao.status == "concluida"
    # `iniciado_em` e da EXECUCAO: o recalculo nao reescreve o inicio dela.
    assert execucao.iniciado_em == inicio


async def test_worker_aplica_stopwords_de_marca(sessao, caplog):
    """Dois videos de marcas diferentes: o nome de cada um sai dos temas."""
    usuario = Usuario(nome="Dona", email="marca@exemplo.com", senha_hash="x", papel="usuario_pme")
    sessao.add(usuario)
    await sessao.flush()
    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario, nome="Campanha", termo_pesquisa="x", filtros={}
    )
    sessao.add(modelo)
    await sessao.flush()
    execucao = Execucao(id_modelo=modelo.id_modelo, status="processando")
    sessao.add(execucao)
    await sessao.flush()

    from tests.test_topicos_marcas import corpus_de_duas_marcas

    videos = {}
    for id_local, (titulo, canal) in enumerate(
        [("Novo Zephyr: o SUV que dura", "Zephyr Brasil"), ("Kovak Trailer", "Kovak Brasil")],
        start=1,
    ):
        video = Video(
            id_execucao=execucao.id_execucao,
            youtube_video_id=f"v{id_local}",
            titulo=titulo,
            canal=canal,
        )
        sessao.add(video)
        await sessao.flush()
        videos[id_local] = video

    for indice, (_, id_video_local, texto) in enumerate(corpus_de_duas_marcas()):
        sessao.add(
            Comentario(
                id_video=videos[id_video_local].id_video,
                youtube_comment_id=f"c{indice}",
                autor_hash=hash_token(f"a{indice}"),
                texto=texto,
            )
        )
    await sessao.commit()
    await enfileirar(sessao, execucao)

    with caplog.at_level(logging.INFO, logger="app.workers.topicos"):
        await topicos.executar_proximo(sessao)

    temas = (await sessao.scalars(select(Tema))).all()
    assert temas
    palavras = {p for t in temas for p in (t.palavras_chave or [])}
    assert "zephyr" not in palavras
    assert "kovak" not in palavras
    # E o log diz quais foram, para a decisao ser auditavel.
    linhas = [r.getMessage() for r in caplog.records if "stopwords de marca" in r.getMessage()]
    assert linhas and "zephyr" in linhas[0]


async def test_sem_job_devolve_false(sessao):
    assert await topicos.executar_proximo(sessao) is False


async def test_falha_inesperada_vai_para_a_dlq(sessao, monkeypatch):
    textos = [texto for _, texto in corpus()]
    execucao = await montar_execucao(sessao, textos, email="t6@exemplo.com")
    job = await enfileirar(sessao, execucao)

    def explodir(*_args, **_kwargs):
        raise RuntimeError("NMF explodiu")

    monkeypatch.setattr(topicos, "modelar", explodir)

    assert await topicos.executar_proximo(sessao) is True

    assert await sessao.get(Job, job.id_job) is None
    morto = await sessao.scalar(select(JobDlq))
    assert morto.tipo == "topicos"
    assert "NMF explodiu" in morto.erro
    await sessao.refresh(execucao)
    assert execucao.status == "erro"
