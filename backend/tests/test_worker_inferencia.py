"""Testes do worker de inferência: ciclo da execução, idempotência e o portão do léxico.

Dados sintéticos em tudo. O SentiLex real tem 6,9 MB e está fora do git, então os
testes do classificador léxico montam um arquivo de mentira no formato do recurso —
o que está sob teste é o parser, o portão do sha256 e a justificativa, não o conteúdo
do léxico publicado (isso é `ml/tests/test_lexico.py`).

O teste ponta a ponta roda em SQLite, com a coleta simulada por dublê: nenhum teste
toca no Supabase nem gasta cota da YouTube API.
"""

import logging

import pytest
from lexico import carregar
from sqlalchemy import select

from app.core.security import hash_token
from app.inferencia import lexico as lexico_producao
from app.inferencia.base import (
    SENTIMENTOS_VALIDOS,
    Classificacao,
    Classificador,
    ClassificadorIndisponivel,
    DescritorVersao,
)
from app.inferencia.lexico import ClassificadorLexico
from app.inferencia.versao import garantir_versao
from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video
from app.workers import coleta, fila, inferencia, topicos
from app.workers.youtube import ComentarioColetado, VideoColetado
from tests.test_worker_coleta import ClienteFalso

VIDEO_A = "video-a"
ID_CANAL_AUTOR = "UC_autor_original"


# --------------------------------------------------------------------------- dublês


class ClassificadorFalso(Classificador):
    """Dublê da interface. Registra o que recebeu e devolve o combinado.

    Existe para provar que o worker é transporte: se ele dependesse do léxico, este
    dublê não bastaria e os testes de ciclo precisariam do arquivo de 6,9 MB.
    """

    def __init__(
        self,
        *,
        sentimento: str = "positivo",
        justificativa: str | None = "porque sim",
        versao_preprocessamento: str | None = None,
        erro: Exception | None = None,
    ) -> None:
        from preprocessamento import VERSAO

        self._sentimento = sentimento
        self._justificativa = justificativa
        self._versao_pre = versao_preprocessamento or VERSAO
        self._erro = erro
        self.textos_recebidos: list[str] = []

    @property
    def descritor(self) -> DescritorVersao:
        return DescritorVersao(
            nome_modelo="classificador-falso",
            versao="9.9.9",
            proveniencia={"metodo": "dublê de teste"},
        )

    @property
    def versao_preprocessamento(self) -> str:
        return self._versao_pre

    def classificar(self, texto_modelo: str) -> Classificacao:
        self.textos_recebidos.append(texto_modelo)
        if self._erro is not None:
            raise self._erro
        return Classificacao(sentimento=self._sentimento, justificativa=self._justificativa)


# --------------------------------------------------------------------------- cenário


async def montar_execucao_com_comentarios(sessao, textos: list[str]) -> Execucao:
    """Cria usuário -> modelo -> execução -> vídeo -> comentários.

    É o estado em que a coleta deixa o banco: o cenário dos testes de inferência
    começa depois dela, sem repetir o dublê da YouTube API.
    """
    usuario = Usuario(
        nome="Dona",
        email=f"inferencia{id(textos)}@exemplo.com",
        senha_hash="x",
        papel="usuario_pme",
    )
    sessao.add(usuario)
    await sessao.flush()

    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario,
        nome="Campanha",
        termo_pesquisa="tênis",
        filtros={"videos": [VIDEO_A]},
    )
    sessao.add(modelo)
    await sessao.flush()

    execucao = Execucao(id_modelo=modelo.id_modelo, status="processando")
    sessao.add(execucao)
    await sessao.flush()

    video = Video(
        id_execucao=execucao.id_execucao,
        youtube_video_id=VIDEO_A,
        titulo="Campanha de verão",
        canal="Loja Exemplo",
    )
    sessao.add(video)
    await sessao.flush()

    for indice, texto in enumerate(textos):
        sessao.add(
            Comentario(
                id_video=video.id_video,
                youtube_comment_id=f"c{indice}",
                autor_hash=hash_token(ID_CANAL_AUTOR),
                texto=texto,
            )
        )
    await sessao.commit()
    await sessao.refresh(execucao)
    return execucao


async def enfileirar_inferencia(sessao, execucao: Execucao) -> Job:
    job = Job(tipo="inferencia", id_execucao=execucao.id_execucao, status="pendente")
    sessao.add(job)
    await sessao.commit()
    await sessao.refresh(job)
    return job


# --------------------------------------------------------------------------- caminho feliz


async def test_grava_uma_analise_por_comentario(sessao):
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei", "detestei", "sei la"])
    await enfileirar_inferencia(sessao, execucao)
    classificador = ClassificadorFalso(sentimento="neutro")

    assert await inferencia.executar_proximo(sessao, classificador) is True

    analises = (await sessao.scalars(select(AnaliseSentimento))).all()
    comentarios = (await sessao.scalars(select(Comentario))).all()
    assert len(analises) == len(comentarios) == 3
    assert {a.id_comentario for a in analises} == {c.id_comentario for c in comentarios}
    assert all(a.sentimento == "neutro" for a in analises)


async def test_analise_aponta_para_a_versao_que_a_produziu(sessao):
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei"])
    await enfileirar_inferencia(sessao, execucao)

    await inferencia.executar_proximo(sessao, ClassificadorFalso())

    versao = await sessao.scalar(select(VersaoModelo))
    assert versao.nome_modelo == "classificador-falso"
    assert versao.versao == "9.9.9"
    # A proveniência entra sob chave própria: `metricas_avaliacao` vazio seria lido
    # como "avaliado e deu zero", e a avaliação do Capítulo 5 ainda não existe.
    assert versao.metricas_avaliacao == {"proveniencia": {"metodo": "dublê de teste"}}

    analise = await sessao.scalar(select(AnaliseSentimento))
    assert analise.id_versao_modelo == versao.id_versao


async def test_justificativa_e_persistida_e_tema_fica_nulo(sessao):
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei"])
    await enfileirar_inferencia(sessao, execucao)

    await inferencia.executar_proximo(sessao, ClassificadorFalso(justificativa="ótimo (+1)"))

    analise = await sessao.scalar(select(AnaliseSentimento))
    assert analise.justificativa == "ótimo (+1)"
    # Tema é do worker de tópicos, que ainda não existe. Inferência não inventa tema.
    assert analise.tema is None


async def test_o_classificador_recebe_o_texto_pre_processado(sessao):
    """A entrada é `preparar_texto`, o mesmo do treino (CLAUDE.md Seção 3).

    Aplicado no worker, e não na implementação: é o que garante que léxico e BERTimbau
    leiam exatamente o mesmo texto, para a comparação do Capítulo 5 medir método.
    """
    execucao = await montar_execucao_com_comentarios(sessao, ["que  produto… \U0001f60d"])
    await enfileirar_inferencia(sessao, execucao)
    classificador = ClassificadorFalso()

    await inferencia.executar_proximo(sessao, classificador)

    recebido = classificador.textos_recebidos[0]
    assert "\U0001f60d" not in recebido  # emoji convertido em palavra
    assert "…" not in recebido  # reticências tipográficas normalizadas
    assert "  " not in recebido  # espaço duplo colapsado

    # O banco continua guardando o ORIGINAL; o texto preparado é derivado.
    comentario = await sessao.scalar(select(Comentario))
    assert comentario.texto == "que  produto… \U0001f60d"


async def test_execucao_sem_comentario_conclui_sem_analise(sessao):
    """Todos os vídeos com comentário desabilitado: zero é resultado, não erro."""
    execucao = await montar_execucao_com_comentarios(sessao, [])
    job = await enfileirar_inferencia(sessao, execucao)

    assert await inferencia.executar_proximo(sessao, ClassificadorFalso()) is True

    assert (await sessao.scalars(select(AnaliseSentimento))).all() == []
    await sessao.refresh(job)
    assert job.status == "concluida"
    # A execucao segue em 'processando': quem a encerra e a etapa de topicos.
    await sessao.refresh(execucao)
    assert execucao.status == "processando"


async def test_executar_proximo_sem_job_devolve_false(sessao):
    assert await inferencia.executar_proximo(sessao, ClassificadorFalso()) is False


async def test_ignora_job_de_outro_tipo(sessao):
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei"])
    job = await enfileirar_inferencia(sessao, execucao)
    job.tipo = "coleta"
    await sessao.commit()

    assert await inferencia.executar_proximo(sessao, ClassificadorFalso()) is False


# --------------------------------------------------------------------------- ciclo da execução


async def test_inferencia_publica_topicos_e_mantem_execucao_processando(sessao):
    """A inferencia deixou de ser a ultima etapa quando o worker de topicos entrou.

    Ela agora passa o bastao: publica `topicos` na MESMA transacao em que se
    conclui, e a execucao so fecha no fim da cadeia.
    """
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei"])
    job = await enfileirar_inferencia(sessao, execucao)

    await inferencia.executar_proximo(sessao, ClassificadorFalso())

    await sessao.refresh(job)
    assert job.status == "concluida"
    await sessao.refresh(execucao)
    assert execucao.status == "processando"
    assert execucao.concluido_em is None

    seguinte = (await sessao.scalars(select(Job).where(Job.status == "pendente"))).all()
    assert [j.tipo for j in seguinte] == ["topicos"]
    assert seguinte[0].id_execucao == execucao.id_execucao


async def test_reivindicar_nao_reescreve_o_inicio_da_execucao(sessao):
    """`iniciado_em` é da EXECUÇÃO, não da etapa.

    Sobrescrever a cada job faria a duração que o painel mostra medir só a última
    etapa — a coleta, que é a parte demorada, desapareceria da conta.
    """
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei"])
    await enfileirar_inferencia(sessao, execucao)

    inicio_da_coleta = execucao.iniciado_em
    assert inicio_da_coleta is None  # o cenário monta a execução sem início ainda

    primeiro = await fila.reivindicar(sessao, "inferencia")
    await sessao.refresh(execucao)
    marcado = execucao.iniciado_em
    assert marcado is not None

    # Segunda etapa da mesma execução não reescreve o início.
    await fila.concluir(sessao, primeiro)
    segundo = Job(tipo="inferencia", id_execucao=execucao.id_execucao, status="pendente")
    sessao.add(segundo)
    await sessao.commit()

    await fila.reivindicar(sessao, "inferencia")
    await sessao.refresh(execucao)
    assert execucao.iniciado_em == marcado


# --------------------------------------------------------------------------- idempotência


async def test_reprocessar_nao_duplica_analise(sessao):
    """Reprocessar uma execução não duplica nem quebra.

    `UNIQUE (id_comentario)` já proibiria a segunda linha, com IntegrityError — o
    worker precisa não CHEGAR lá, porque o erro mataria o job na DLQ e marcaria uma
    execução perfeitamente boa como 'erro'.
    """
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei", "detestei"])
    await enfileirar_inferencia(sessao, execucao)
    await inferencia.executar_proximo(sessao, ClassificadorFalso())

    # Segunda passada: mesmo job enfileirado de novo, mesma execução.
    await enfileirar_inferencia(sessao, execucao)
    segundo = ClassificadorFalso()
    assert await inferencia.executar_proximo(sessao, segundo) is True

    analises = (await sessao.scalars(select(AnaliseSentimento))).all()
    assert len(analises) == 2
    # Nem chamou o classificador: os dois comentários já tinham análise.
    assert segundo.textos_recebidos == []
    assert (await sessao.scalars(select(JobDlq))).all() == []


async def test_retomada_classifica_so_o_que_faltou(sessao):
    """Metade gravada por uma queda anterior: a segunda passada completa o resto."""
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei", "detestei", "sei la"])
    versao = await garantir_versao(sessao, ClassificadorFalso().descritor)

    primeiro = await sessao.scalar(select(Comentario).order_by(Comentario.id_comentario))
    sessao.add(
        AnaliseSentimento(
            id_comentario=primeiro.id_comentario,
            id_versao_modelo=versao.id_versao,
            sentimento="positivo",
        )
    )
    await sessao.commit()

    await enfileirar_inferencia(sessao, execucao)
    classificador = ClassificadorFalso()
    await inferencia.executar_proximo(sessao, classificador)

    assert len(classificador.textos_recebidos) == 2  # só os dois que faltavam
    assert len((await sessao.scalars(select(AnaliseSentimento))).all()) == 3


async def test_versao_de_modelo_nao_e_recriada(sessao):
    """Duas execuções com o mesmo classificador apontam para a MESMA linha de versão."""
    descritor = ClassificadorFalso().descritor

    primeira = await garantir_versao(sessao, descritor)
    segunda = await garantir_versao(sessao, descritor)

    assert primeira.id_versao == segunda.id_versao
    assert len((await sessao.scalars(select(VersaoModelo))).all()) == 1


async def test_versoes_diferentes_ganham_linhas_diferentes(sessao):
    """Trocar de classificador não reescreve o histórico: a versão antiga continua lá."""
    lexica = DescritorVersao(nome_modelo="lexico-sentilex", versao="1.0.0", proveniencia={})
    bertimbau = DescritorVersao(nome_modelo="bertimbau-emi", versao="1.0.0", proveniencia={})

    uma = await garantir_versao(sessao, lexica)
    outra = await garantir_versao(sessao, bertimbau)

    assert uma.id_versao != outra.id_versao
    assert len((await sessao.scalars(select(VersaoModelo))).all()) == 2


# --------------------------------------------------------------------------- falhas


async def test_erro_do_classificador_vai_para_a_dlq_sem_retentativa(sessao):
    """Erro local não é transitório: repetir só atrasa a ida para a DLQ."""
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei"])
    job = await enfileirar_inferencia(sessao, execucao)
    classificador = ClassificadorFalso(erro=RuntimeError("modelo explodiu"))

    assert await inferencia.executar_proximo(sessao, classificador) is True

    # Uma única chamada: nenhuma retentativa.
    assert len(classificador.textos_recebidos) == 1
    assert await sessao.get(Job, job.id_job) is None

    morto = await sessao.scalar(select(JobDlq))
    assert morto.id_job == job.id_job
    assert morto.tipo == "inferencia"
    assert "modelo explodiu" in morto.erro

    await sessao.refresh(execucao)
    assert execucao.status == "erro"
    assert (await sessao.scalars(select(AnaliseSentimento))).all() == []


async def test_sentimento_fora_do_check_falha_antes_de_gravar(sessao):
    """O bug da regra 5 do CLAUDE.md (ordem de rótulos) aparecendo alto.

    Sem esta conferência, um rótulo fora do CHECK viraria IntegrityError no commit do
    lote, e a mensagem do banco não diria qual implementação o produziu.
    """
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei"])
    await enfileirar_inferencia(sessao, execucao)

    await inferencia.executar_proximo(sessao, ClassificadorFalso(sentimento="POSITIVO"))

    morto = await sessao.scalar(select(JobDlq))
    assert "POSITIVO" in morto.erro
    assert "classificador-falso" in morto.erro
    assert (await sessao.scalars(select(AnaliseSentimento))).all() == []


async def test_log_de_inferencia_carrega_o_id_execucao(sessao, caplog):
    """Convenção da Seção 7: sem o id_execucao não se depura execução concorrente."""
    execucao = await montar_execucao_com_comentarios(sessao, ["adorei"])
    await enfileirar_inferencia(sessao, execucao)

    with caplog.at_level(logging.INFO, logger="app.workers.inferencia"):
        await inferencia.executar_proximo(sessao, ClassificadorFalso())

    linhas = [r.getMessage() for r in caplog.records]
    assert linhas
    assert all(f"id_execucao={execucao.id_execucao}" in linha for linha in linhas)


# ------------------------------------------------------------ portão do pré-processamento


def test_validar_recusa_versao_de_preprocessamento_divergente():
    """CLAUDE.md regra 5: divergência é erro alto, não queda silenciosa de acurácia."""
    classificador = ClassificadorFalso(versao_preprocessamento="0.0.1")

    with pytest.raises(ClassificadorIndisponivel) as erro:
        classificador.validar()

    assert "0.0.1" in str(erro.value)
    from preprocessamento import VERSAO

    assert VERSAO in str(erro.value)


def test_validar_aceita_versao_igual():
    ClassificadorFalso().validar()  # não levanta


# --------------------------------------------------------------------------- classificador léxico


LEXICO_SINTETICO = "\n".join(
    [
        "# arquivo de mentira no formato do SentiLex-PT02",
        "ótimo.PoS=Adj;TG=HUM:N0;POL:N0=1;ANOT=JALC",
        "caro.PoS=Adj;TG=HUM:N0;POL:N0=-1;ANOT=JALC",
        "lixo.PoS=N;TG=HUM:N0;POL:N0=-1;ANOT=JALC",
        "produto.PoS=N;TG=HUM:N0;POL:N0=0;ANOT=JALC",
        "adorei,adorar.PoS=V;FLEX=1s;TG=HUM:N0:N1;POL:N0=0;POL:N1=1;ANOT=MAN",
    ]
)


def sha256_do(caminho) -> str:
    """O hash que o `Lexico` calculou ao ler o arquivo — sem recalcular por fora."""
    return carregar(caminho).sha256


@pytest.fixture
def arquivo_lexico(tmp_path):
    caminho = tmp_path / "SentiLex-flex-PT02.txt"
    caminho.write_text(LEXICO_SINTETICO, encoding="utf-8")
    return caminho


@pytest.fixture
def classificador_lexico(arquivo_lexico, monkeypatch):
    """Carrega o léxico sintético, ensinando o portão a esperar o hash dele.

    O hash esperado em produção é o do arquivo de 6,9 MB, que está fora do git. Trocar
    a constante aqui é o que permite exercitar o CAMINHO FELIZ do portão; o caminho de
    falha é testado com a constante real, sem monkeypatch.
    """
    monkeypatch.setattr(lexico_producao, "SHA256_ESPERADO", sha256_do(arquivo_lexico))
    return ClassificadorLexico.de_arquivo(arquivo_lexico)


def test_lexico_soma_polaridade_e_devolve_o_sinal(classificador_lexico):
    assert classificador_lexico.classificar("produto ótimo").sentimento == "positivo"
    assert classificador_lexico.classificar("que lixo").sentimento == "negativo"
    # Empate: os dois lados se anulam.
    assert classificador_lexico.classificar("ótimo mas caro").sentimento == "neutro"


def test_lexico_grava_as_palavras_que_decidiram_o_rotulo(classificador_lexico):
    """É o que a tela mostra em "Por que foi classificado assim"."""
    classificacao = classificador_lexico.classificar("ótimo mas caro")

    assert classificacao.justificativa == "ótimo (+1), caro (-1)"


def test_lexico_distingue_neutro_por_ignorancia_de_neutro_por_empate(classificador_lexico):
    """Os dois viram `neutro`, mas são fracassos diferentes — o usuário tem que ler qual."""
    ignorancia = classificador_lexico.classificar("mano do céu")
    empate = classificador_lexico.classificar("ótimo mas caro")

    assert ignorancia.sentimento == empate.sentimento == "neutro"
    assert ignorancia.justificativa == lexico_producao.SEM_COBERTURA
    assert empate.justificativa == "ótimo (+1), caro (-1)"


def test_justificativa_longa_e_truncada_com_contagem(classificador_lexico):
    """A explicação fica ao lado do comentário na tela: lista sem fim não explica."""
    texto = " ".join(["ótimo"] * 12)

    justificativa = classificador_lexico.classificar(texto).justificativa

    assert justificativa.count("ótimo") == lexico_producao.MAX_TERMOS_NA_JUSTIFICATIVA
    assert justificativa.endswith("e mais 4")


def test_lexico_declara_a_proveniencia_do_recurso(classificador_lexico, arquivo_lexico):
    """O sha256 na linha de VERSOES_MODELO é o que prova de qual arquivo saiu o rótulo."""
    descritor = classificador_lexico.descritor

    assert descritor.nome_modelo == "lexico-sentilex"
    recurso = descritor.proveniencia["recurso"]
    assert recurso["nome"] == "SentiLex-PT02"
    assert recurso["sha256"] == sha256_do(arquivo_lexico)
    # As cinco entradas do arquivo sintético entram no índice: "produto" tem
    # polaridade 0 e é conhecida do léxico — ela só não move a soma.
    assert recurso["entradas_lidas"] == recurso["entradas_utilizaveis"] == 5


def test_arquivo_ausente_falha_com_o_caminho_esperado(tmp_path):
    """Requisito: falha clara na inicialização, dizendo onde ele era esperado."""
    faltando = tmp_path / "nao-baixado" / "SentiLex-flex-PT02.txt"

    with pytest.raises(ClassificadorIndisponivel) as erro:
        ClassificadorLexico.de_arquivo(faltando)

    mensagem = str(erro.value)
    assert str(faltando) in mensagem
    assert "ml/lexico/README.md" in mensagem


def test_sha256_diferente_recusa_o_arquivo(arquivo_lexico):
    """Outro espelho, download truncado ou o `lem` no lugar do `flex`.

    Sem esta conferência a classificação de produção mudaria em silêncio, e o número
    do Capítulo 5 passaria a descrever um recurso que não é mais o que está rodando.
    """
    with pytest.raises(ClassificadorIndisponivel) as erro:
        ClassificadorLexico.de_arquivo(arquivo_lexico)

    mensagem = str(erro.value)
    assert lexico_producao.SHA256_ESPERADO in mensagem
    assert sha256_do(arquivo_lexico) in mensagem
    assert str(arquivo_lexico) in mensagem


def test_rotulos_do_lexico_batem_com_o_check_do_banco():
    """Espelho do teste do `ml/`: o pacote compartilhado repete os três rótulos.

    O preço de não importar `ml.config` (para o backend poder importar o pacote) é
    este teste dos dois lados — aqui contra o CHECK de ANALISES_SENTIMENTO.
    """
    from lexico import NEGATIVO, NEUTRO, POSITIVO

    assert {POSITIVO, NEGATIVO, NEUTRO} == set(SENTIMENTOS_VALIDOS)


# --------------------------------------------------------------------------- ponta a ponta


async def test_ponta_a_ponta_coleta_simulada_ate_execucao_concluida(sessao):
    """Coleta (dublê da YouTube API) -> inferência -> execução concluída.

    O que o teste prova de fato é a COSTURA: que a coleta publica a etapa seguinte,
    que a execução só fecha no fim da cadeia e que sobra uma análise por comentário.
    Em SQLite, sem Supabase e sem cota (CLAUDE.md: não rode contra o Supabase ainda).
    """
    usuario = Usuario(
        nome="Dona", email="pontaaponta@exemplo.com", senha_hash="x", papel="usuario_pme"
    )
    sessao.add(usuario)
    await sessao.flush()
    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario,
        nome="Campanha",
        termo_pesquisa="tênis",
        filtros={"videos": [VIDEO_A]},
    )
    sessao.add(modelo)
    await sessao.flush()
    execucao = Execucao(id_modelo=modelo.id_modelo, status="pendente")
    sessao.add(execucao)
    await sessao.flush()
    sessao.add(
        Job(
            tipo="coleta",
            id_execucao=execucao.id_execucao,
            status="pendente",
            payload={"id_modelo": modelo.id_modelo, "filtros": modelo.filtros},
        )
    )
    await sessao.commit()

    cliente = ClienteFalso(
        videos=[
            VideoColetado(
                youtube_video_id=VIDEO_A,
                titulo="Campanha de verão",
                canal="Loja Exemplo",
                publicado_em=None,
                visualizacoes=1000,
                curtidas=50,
            )
        ],
        comentarios={
            VIDEO_A: [
                ComentarioColetado(
                    youtube_comment_id=f"c{indice}",
                    autor_hash=hash_token(ID_CANAL_AUTOR),
                    texto=texto,
                    publicado_em=None,
                )
                for indice, texto in enumerate(["adorei o anúncio", "que lixo", "sei la"])
            ]
        },
    )

    # 1. coleta
    assert await coleta.executar_proximo(sessao, cliente) is True
    await sessao.refresh(execucao)
    assert execucao.status == "processando"
    assert len((await sessao.scalars(select(Comentario))).all()) == 3

    # 2. inferência, do job que a coleta publicou
    assert await inferencia.executar_proximo(sessao, ClassificadorFalso()) is True
    await sessao.refresh(execucao)
    assert execucao.status == "processando"  # ainda falta a etapa de tópicos

    # 3. tópicos, do job que a inferência publicou. Três comentários é menos que o
    #    mínimo, então ela conclui sem tema — e é ela que encerra a execução.
    assert await topicos.executar_proximo(sessao) is True

    # 4. execução concluída, uma análise por comentário
    await sessao.refresh(execucao)
    assert execucao.status == "concluida"
    assert execucao.concluido_em is not None
    assert (await sessao.scalars(select(Tema))).all() == []

    analises = (await sessao.scalars(select(AnaliseSentimento))).all()
    comentarios = (await sessao.scalars(select(Comentario))).all()
    assert len(analises) == len(comentarios) == 3
    assert {a.id_comentario for a in analises} == {c.id_comentario for c in comentarios}

    # Fila limpa e nada na DLQ.
    assert (await sessao.scalars(select(Job).where(Job.status == "pendente"))).all() == []
    assert (await sessao.scalars(select(JobDlq))).all() == []
