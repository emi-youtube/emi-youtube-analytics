"""Filtro de idioma da coleta (`app/workers/idioma.py`).

A amostra abaixo foi escrita para este teste: comentários do tipo que aparece em vídeos
publicitários brasileiros, com gíria, abreviação, emoji e ironia, e os vizinhos que
confundem (espanhol, inglês, "que lindo", português de Portugal). O que importa mais é a
primeira asserção: nenhum português sai. O resto mede quanto do estrangeiro é pego.
"""

import pytest

from app.workers import idioma

PORTUGUES = [
    "que propaganda linda, chorei",
    "caro demais pra qualidade que tem",
    "tem em outra cor?",
    "kkkkkkk mds",
    "top demais esse comercial",
    "comprei e veio com defeito, nunca mais",
    "a atriz é linda demais 😍",
    "q isso mano, mt bom",
    "vdd, achei mó paia",
    "amei",
    "quanto custa o frete pra SP?",
    "essa marca nunca decepciona",
    "vi esse anúncio umas 5 vezes hoje",
    "nossa que comercial chato",
    "alguém sabe a música?",
    "Parabéns pela campanha!!!",
    "pq ta tao caro?",
    "meu sonho esse carro",
    "a entrega demorou mas o produto é ótimo",
    "lindo",
    "que lindo",
    "show de bola",
    "rs",
    "😍😍😍",
    "muito bom",
    "esse comercial me pegou de jeito",
    "alguém mais achou caro demais?",
    "melhor propaganda do ano sem dúvidas",
    "odeio segunda-feira, mas esse comercial salvou meu dia",
    "o carro é bonito mas o preço tá absurdo",
    "quero muito comprar esse tênis",
    "a música é de qual artista?",
    "isto é fantástico, adorei o anúncio",
    "gostei bué deste anúncio",
    "chegou rapidinho, recomendo demais",
    "nunca mais compro nessa loja, atendimento horrível",
    "eles poderiam fazer um modelo mais barato né",
    "que trilha sonora perfeita",
    "first",
    "Brasil 🇧🇷🇧🇷",
    "excelente produto",
    "me encanta essa marca",
    "cadê o link?",
    "Quem tá vendo em 2026?",
    "ficou incrível a fotografia do comercial",
    "a propaganda é boa mas o produto deixa a desejar",
    "gente que coisa mais fofa",
    "esse anúncio aparece toda hora no meu feed",
    "o atendimento resolveu meu problema rapidinho",
    "não curti a voz do narrador",
]

ESPANHOL = [
    "que bonito anuncio, me encanta",
    "es demasiado caro para lo que es",
    "¿alguien sabe cómo se llama la canción?",
    "jajaja muy bueno",
    "me gustó mucho el comercial",
    "qué asco de publicidad",
    "lo quiero ya",
    "saludos desde México",
    "excelente producto, lo recomiendo",
    "no me gusta nada",
    "este anuncio es una obra de arte",
    "la música está buenísima",
    "cuánto cuesta en Argentina?",
    "mi novia me lo regaló y me encanta",
    "muy caro para la calidad que tiene",
    "quién vino por la canción?",
    "el mejor comercial que he visto",
    "qué hermoso todo",
    "pésimo servicio, nunca llegó mi pedido",
    "se ve increíble",
]

INGLES = [
    "this ad is amazing",
    "too expensive for what it is",
    "who is the singer?",
    "lol",
    "love it",
    "worst commercial ever",
    "greetings from the USA",
    "I bought one and it broke",
    "this is the best ad I have seen this year",
    "the song is so good",
    "can't wait to buy it",
    "who else is here in 2026?",
    "great quality, highly recommend",
    "nobody asked for this",
    "the actress is so beautiful",
]


def _com_palavras_suficientes(textos: list[str]) -> list[str]:
    return [t for t in textos if len(idioma._PALAVRA.findall(t)) >= idioma.PALAVRAS_MINIMAS]


def test_nenhum_comentario_em_portugues_sai():
    perdidos = [texto for texto in PORTUGUES if idioma.em_outro_idioma(texto)]
    assert perdidos == []


def test_pega_a_maior_parte_do_espanhol():
    pegos = [texto for texto in ESPANHOL if idioma.em_outro_idioma(texto)]
    # Medido: 17 de 20. O piso deixa folga para uma versão nova do modelo, não para regredir.
    assert len(pegos) >= 15, sorted(set(ESPANHOL) - set(pegos))


def test_pega_todo_o_ingles_com_tres_palavras_ou_mais():
    elegiveis = _com_palavras_suficientes(INGLES)
    assert len(elegiveis) == 13
    assert [texto for texto in elegiveis if not idioma.em_outro_idioma(texto)] == []


@pytest.mark.parametrize("texto", ["lol", "love it", "kkkk", "top", "😍😍😍", "rs", "first", ""])
def test_curto_demais_fica(texto):
    assert idioma.aceitar(texto)


@pytest.mark.parametrize(
    "texto",
    ["이 광고 너무 좋아요", "очень хорошая реклама", "إعلان رائع جدا", "このCMが大好き"],
)
def test_alfabeto_nao_latino_sai(texto):
    assert idioma.em_outro_idioma(texto)


def test_emoji_e_acento_nao_contam_como_alfabeto_estrangeiro():
    assert idioma.aceitar("ação incrível 😍🇧🇷 parabéns à equipe")


def test_portugues_vem_com_probabilidade_e_o_codigo_iso():
    lingua, probabilidade = idioma.idioma_provavel("essa propaganda ficou muito bonita")
    assert lingua == "pt"
    assert 0.5 < probabilidade <= 1.0
