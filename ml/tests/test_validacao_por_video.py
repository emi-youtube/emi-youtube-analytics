"""O diagnóstico por vídeo (`ml/treino/validacao_por_video.py`) faz a conta certa?

O treino de verdade precisa de GPU e do BERTimbau; aqui o treinador é um dublê
injetado, e o que se testa é a conta em volta dele: as dobras, a junção das previsões
fora da dobra, o recorte sem gêmeos, a queda e a regra de leitura.
"""

import json
import random
import string
from collections import Counter

import pytest

from ml.config import CLASSES
from ml.treino.dados import Exemplo
from ml.treino.validacao_por_video import (
    ARQUIVO_BASELINE,
    DOBRAS,
    LIMIAR_QUEDA_RELEVANTE,
    dobras_estratificadas,
    dobras_por_video_do_tfidf,
    ler_queda,
    quedas,
    sem_gemeo_no_treino,
    validar_esquema,
)


def texto_unico(semente: int) -> str:
    """Texto sem parentesco com os outros: letras sorteadas, sem gêmeo por acaso."""
    sorteio = random.Random(semente)
    return " ".join(
        "".join(sorteio.choice(string.ascii_lowercase) for _ in range(6)) for _ in range(5)
    )


def exemplo(id_comentario: int, rotulo: str, texto: str | None = None) -> Exemplo:
    texto = texto or texto_unico(id_comentario)
    return Exemplo(id_comentario=id_comentario, texto=texto, texto_modelo=texto, rotulo=rotulo)


def corpus_por_video(videos: int = 8, por_video: int = 30) -> tuple[list[Exemplo], dict[int, int]]:
    """Cada vídeo tem um sentimento dominante; textos únicos, sem gêmeos."""
    exemplos, grupo = [], {}
    proximo = 1
    for video in range(videos):
        for posicao in range(por_video):
            rotulo = CLASSES[(video + (posicao % 5 == 0)) % 3]
            exemplos.append(exemplo(proximo, rotulo))
            grupo[proximo] = video
            proximo += 1
    return exemplos, grupo


# -------------------------------------------------------------- dobras


def test_dobras_estratificadas_tem_tamanhos_iguais_e_mantem_as_classes():
    rotulos = ["positivo"] * 94 + ["negativo"] * 60 + ["neutro"] * 66
    dobra_de = dobras_estratificadas(rotulos)

    tamanhos = Counter(dobra_de)
    assert set(tamanhos) == set(range(1, DOBRAS + 1))
    assert max(tamanhos.values()) - min(tamanhos.values()) <= 1
    for classe, total in Counter(rotulos).items():
        por_dobra = Counter(d for d, r in zip(dobra_de, rotulos, strict=True) if r == classe)
        assert max(por_dobra.values()) - min(por_dobra.values()) <= 1, classe
        assert sum(por_dobra.values()) == total


def test_dobras_estratificadas_sao_reprodutiveis():
    rotulos = [CLASSES[i % 3] for i in range(50)]
    assert dobras_estratificadas(rotulos) == dobras_estratificadas(rotulos)
    assert dobras_estratificadas(rotulos) != dobras_estratificadas(rotulos, semente=7)


def test_dobras_por_video_sao_as_do_tfidf():
    """As mesmas dobras do TF-IDF: cada vídeo numa só, os 14 vídeos, 5 dobras."""
    mapa = dobras_por_video_do_tfidf()
    gravadas = json.loads(ARQUIVO_BASELINE.read_text(encoding="utf-8"))
    dobras = gravadas["validacao_por_grupo"]["por_video_groupkfold"]["dobras"]

    assert len(mapa) == sum(len(dobra["videos"]) for dobra in dobras) == 14
    assert set(mapa.values()) == set(range(1, DOBRAS + 1))
    for dobra in dobras:
        assert {v for v, d in mapa.items() if d == dobra["dobra"]} == set(dobra["videos"])


def test_dobras_por_video_sem_arquivo_para_com_mensagem(tmp_path):
    with pytest.raises(SystemExit, match="treinar_baseline"):
        dobras_por_video_do_tfidf(tmp_path / "nao_existe.json")


# -------------------------------------------------------------- gêmeos


def test_sem_gemeo_no_treino_tira_quem_tem_texto_igual_do_outro_lado():
    treino = [exemplo(1, "positivo", "Amei demais!!!"), exemplo(2, "negativo", "que horror")]
    fora = [exemplo(3, "positivo", "amei demais"), exemplo(4, "neutro", "quando lanca no brasil")]

    assert sem_gemeo_no_treino(fora, treino) == {4}


# -------------------------------------------------------------- a conta inteira


def test_preditor_perfeito_nao_tem_queda():
    exemplos, grupo = corpus_por_video()
    perfeito = lambda treino, fora: [e.rotulo for e in fora]  # noqa: E731

    aleatoria = validar_esquema(
        exemplos, dobras_estratificadas([e.rotulo for e in exemplos]), perfeito
    )
    por_video = validar_esquema(
        exemplos, [grupo[e.id_comentario] % DOBRAS + 1 for e in exemplos], perfeito
    )

    assert aleatoria["fora_da_dobra"]["f1_macro"] == pytest.approx(1.0)
    assert aleatoria["fora_da_dobra"]["n"] == len(exemplos)
    queda = quedas(aleatoria, por_video)
    # A média das dobras pode diferir: o F1 macro do projeto divide por 3 mesmo quando
    # uma dobra por vídeo não tem uma das classes. O agregado fora da dobra não sofre isso.
    assert queda["fora_da_dobra"] == pytest.approx(0.0)
    assert queda["fora_da_dobra_sem_gemeos"] == pytest.approx(0.0)


def test_quem_so_conhece_videos_vistos_cai_na_validacao_por_video():
    """O dublê acerta quando o vídeo apareceu no treino e chuta 'neutro' quando não."""
    exemplos, grupo = corpus_por_video()
    rotulo_do_video = {
        video: Counter(e.rotulo for e in exemplos if grupo[e.id_comentario] == video).most_common(
            1
        )[0][0]
        for video in set(grupo.values())
    }

    def decora_o_video(treino, fora):
        vistos = {grupo[e.id_comentario] for e in treino}
        return [
            rotulo_do_video[grupo[e.id_comentario]]
            if grupo[e.id_comentario] in vistos
            else "neutro"
            for e in fora
        ]

    aleatoria = validar_esquema(
        exemplos, dobras_estratificadas([e.rotulo for e in exemplos]), decora_o_video
    )
    por_video = validar_esquema(
        exemplos,
        [grupo[e.id_comentario] % DOBRAS + 1 for e in exemplos],
        decora_o_video,
        rotulo_de_grupo=lambda e: grupo[e.id_comentario],
    )
    queda = quedas(aleatoria, por_video)

    assert queda["fora_da_dobra"] > 0.3
    assert queda["fora_da_dobra_sem_gemeos"] > 0.3
    assert all(dobra["videos"] for dobra in por_video["dobras"])
    assert ler_queda(queda["fora_da_dobra_sem_gemeos"]).startswith("relevante")


def test_previsoes_a_menos_param_a_conta():
    exemplos, grupo = corpus_por_video(videos=5, por_video=6)
    quebrado = lambda treino, fora: [e.rotulo for e in fora][:-1]  # noqa: E731

    with pytest.raises(RuntimeError, match="previsoes"):
        validar_esquema(exemplos, [grupo[e.id_comentario] + 1 for e in exemplos], quebrado)


def test_gemeos_entre_dobras_saem_do_recorte_sem_gemeos():
    """Um texto repetido em duas dobras conta em 'todos' e some em 'sem gêmeos'."""
    exemplos = [exemplo(i, CLASSES[i % 3]) for i in range(1, 41)]
    exemplos[0] = exemplo(1, "positivo", "top demais esse comercial")
    exemplos[1] = exemplo(2, "positivo", "top demais esse comercial!!")
    dobra_de = [1, 2] + [i % DOBRAS + 1 for i in range(38)]

    resultado = validar_esquema(exemplos, dobra_de, lambda treino, fora: [e.rotulo for e in fora])

    assert resultado["fora_da_dobra"]["n"] == 40
    assert resultado["fora_da_dobra_sem_gemeos"]["n"] == 38


# -------------------------------------------------------------- leitura


def test_sem_exemplo_sem_gemeo_nao_ha_leitura():
    assert ler_queda(None).startswith("sem leitura")


@pytest.mark.parametrize(
    ("queda", "inicio"),
    [
        (0.0, "pequena"),
        (LIMIAR_QUEDA_RELEVANTE - 0.001, "pequena"),
        (LIMIAR_QUEDA_RELEVANTE, "relevante"),
        (0.08, "relevante"),
    ],
)
def test_regra_de_leitura(queda, inicio):
    assert ler_queda(queda).startswith(inicio)


# -------------------------------------------------------------- o laço de treino


def test_treinar_uma_vez_aceita_avaliar_a_ultima_epoca():
    """Sem torch não há laço para testar; com ele, o parâmetro tem de existir."""
    pytest.importorskip("torch")
    import inspect

    from ml.treino.treinar import Resultado, treinar_uma_vez

    assert "selecionar_epoca" in inspect.signature(treinar_uma_vez).parameters
    assert "previstos" in Resultado.__dataclass_fields__
