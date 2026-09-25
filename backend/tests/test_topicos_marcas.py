"""Testes das stopwords de marca por execução.

O corpus sintético imita a situação real: dois vídeos de marcas diferentes, cada
um com o seu nome próprio, e um assunto (`entrega`) que atravessa os dois. O que
os testes exigem é que o nome da marca saia e o assunto compartilhado fique — que
é exatamente a distinção que a validação sobre os vídeos de carros expôs.
"""

import pytest

from app.topicos.marcas import (
    CONCENTRACAO_MINIMA,
    MINIMO_DE_COMENTARIOS_PARA_JULGAR,
    MINIMO_DE_VIDEOS,
    VideoDaExecucao,
    candidatas,
    stopwords_de_marca,
)
from app.topicos.modelo import modelar

VIDEO_A = VideoDaExecucao(id_video=1, titulo="Novo Zephyr: o SUV que dura", canal="Zephyr Brasil")
VIDEO_B = VideoDaExecucao(id_video=2, titulo="Kovak Trailer de lançamento", canal="Kovak Brasil")


def corpus_de_duas_marcas(repeticoes: int = 16) -> list[tuple[int, int, str]]:
    """`(id_comentario, id_video, texto)`.

    "zephyr" e "kovak" ficam cada um no seu vídeo; "entrega" e "trailer"
    aparecem nos dois. `repeticoes` passa do mínimo de 100 comentários que a
    modelagem exige, senão não haveria tema para comparar.
    """
    # As frases SEM a marca existem para segurar a frequencia dela abaixo do
    # `max_df` do vetorizador (40%): uma marca presente em metade dos documentos
    # seria cortada como stopword do corpus antes de o NMF a ver, e o teste
    # mediria o corte de frequencia em vez das stopwords de marca.
    comentarios: list[tuple[int, int, str]] = []
    identificador = 1
    for _ in range(repeticoes):
        for texto in (
            "o zephyr ficou lindo demais",
            "comprei um zephyr esse mes",
            "a entrega atrasou duas semanas",
            "entrega rapida, chegou no prazo",
            "acabamento caprichado e confortavel",
            "esse trailer ficou otimo de assistir",
        ):
            comentarios.append((identificador, 1, texto))
            identificador += 1
        for texto in (
            "o kovak e bonito por fora",
            "kovak tem acabamento fraco",
            "a entrega demorou muito aqui",
            "entrega no prazo, recomendo bastante",
            "acabamento simples mas confortavel",
            "trailer ficou bom de assistir",
        ):
            comentarios.append((identificador, 2, texto))
            identificador += 1
    return comentarios


# --------------------------------------------------------------------------- candidatas


def test_candidatas_saem_do_canal_e_do_titulo():
    resultado = candidatas([VIDEO_A, VIDEO_B])

    assert "zephyr" in resultado
    assert "kovak" in resultado
    assert "trailer" in resultado  # está no título do B


def test_candidatas_ignoram_stopword_e_token_curto():
    resultado = candidatas([VIDEO_A, VIDEO_B])

    assert "novo" not in resultado  # stopword
    assert "que" not in resultado
    assert all(len(p) >= 3 for p in resultado)


# --------------------------------------------------------------------------- medição


def test_nome_de_marca_vira_stopword():
    resultado = stopwords_de_marca([VIDEO_A, VIDEO_B], corpus_de_duas_marcas())

    assert "zephyr" in resultado.palavras
    assert "kovak" in resultado.palavras


def test_palavra_que_atravessa_os_videos_e_poupada():
    """O ponto do módulo: "trailer" está no título e MESMO ASSIM sobrevive.

    Sem a medição, tirar toda palavra de título apagaria o assunto junto com a
    marca — foi o risco que motivou o critério.
    """
    resultado = stopwords_de_marca([VIDEO_A, VIDEO_B], corpus_de_duas_marcas())

    assert "trailer" not in resultado.palavras
    poupadas = {c.palavra for c in resultado.mantidas}
    assert "trailer" in poupadas


def test_a_medicao_fica_registrada_para_explicar_a_decisao():
    resultado = stopwords_de_marca([VIDEO_A, VIDEO_B], corpus_de_duas_marcas())

    por_palavra = {c.palavra: c for c in resultado.avaliadas}
    assert por_palavra["zephyr"].concentracao >= CONCENTRACAO_MINIMA
    assert por_palavra["trailer"].concentracao < CONCENTRACAO_MINIMA
    assert por_palavra["zephyr"].id_video_dominante == 1
    assert por_palavra["kovak"].id_video_dominante == 2


def test_palavra_rara_nao_e_julgada():
    """Concentração de duas ocorrências não significa nada."""
    comentarios = [
        (1, 1, "zephyr zephyr zephyr"),
        (2, 1, "zephyr de novo"),
        (3, 2, "kovak aqui"),
    ]

    resultado = stopwords_de_marca([VIDEO_A, VIDEO_B], comentarios)

    por_palavra = {c.palavra: c for c in resultado.avaliadas}
    assert por_palavra["zephyr"].comentarios < MINIMO_DE_COMENTARIOS_PARA_JULGAR
    assert "zephyr" not in resultado.palavras


# --------------------------------------------------------------------------- guardas


def test_execucao_de_um_video_nao_usa_o_criterio():
    """Com um vídeo, TUDO está 100% concentrado nele — o critério apagaria o corpus."""
    comentarios = [(i, 1, "o zephyr e lindo e a entrega foi rapida") for i in range(1, 30)]

    resultado = stopwords_de_marca([VIDEO_A], comentarios)

    assert resultado.palavras == frozenset()
    assert resultado.motivo is not None
    assert str(MINIMO_DE_VIDEOS) in resultado.motivo


def test_sem_comentario_nao_quebra():
    resultado = stopwords_de_marca([VIDEO_A, VIDEO_B], [])

    assert resultado.palavras == frozenset()


# --------------------------------------------------------------------------- efeito no tema


def test_marca_sai_dos_temas_e_o_assunto_fica():
    """Antes e depois, sobre o mesmo corpus: é o que a validação mediu em grande."""
    comentarios = corpus_de_duas_marcas()
    so_texto = [(id_comentario, texto) for id_comentario, _, texto in comentarios]
    marcas = stopwords_de_marca([VIDEO_A, VIDEO_B], comentarios)

    antes = modelar(so_texto)
    depois = modelar(so_texto, stopwords_extra=marcas.palavras)

    palavras_antes = {p for t in antes.temas for p in t.palavras_chave}
    palavras_depois = {p for t in depois.temas for p in t.palavras_chave}

    assert "zephyr" in palavras_antes
    assert "zephyr" not in palavras_depois
    assert "kovak" not in palavras_depois
    # O assunto compartilhado continua descrevendo algum tema.
    assert "entrega" in palavras_depois


def test_stopwords_de_marca_nao_vazam_entre_execucoes():
    """São de UMA execução: "renault" é ruído na campanha da Renault e assunto
    legítimo na campanha de uma concessionária multimarca."""
    from app.topicos.texto import STOPWORDS

    resultado = stopwords_de_marca([VIDEO_A, VIDEO_B], corpus_de_duas_marcas())

    assert resultado.palavras
    assert not (resultado.palavras & STOPWORDS)


@pytest.mark.parametrize("quantos_videos", [0, 1])
def test_abaixo_do_minimo_de_videos_devolve_vazio(quantos_videos):
    videos = [VIDEO_A][:quantos_videos]

    assert stopwords_de_marca(videos, corpus_de_duas_marcas()).palavras == frozenset()
