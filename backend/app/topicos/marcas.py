"""Stopwords de MARCA, calculadas por execução.

**O problema.** Na validação sobre os vídeos de carros, o NMF separou os temas
por marca — "renault / boreal", "chevrolet / sonic" — em vez de por assunto. A
causa é mecânica: o nome da marca só aparece nos comentários de UM vídeo, então
é o token mais discriminativo do corpus e o método o usa como eixo. A
demonstração da banca compara vídeo próprio com vídeo de concorrente, que é
exatamente essa situação.

**A solução.** As palavras do nome do canal e do título de cada vídeo DAQUELA
execução entram como stopwords, mas **só as que a medição confirmar**.

**Por que a medição é obrigatória.** "Trailer" está no título de dois vídeos de
jogos e é assunto legítimo — foi palavra-chave do tema "dublado / trailer /
edward". Tirar toda palavra de título às cegas apagaria o tema junto com a
marca. O que distingue um do outro não é a palavra estar no título: é **onde ela
aparece nos comentários**. Nome de marca se concentra num vídeo; assunto
atravessa os vídeos.

Então o critério é:

1. **candidata** — a palavra está no nome do canal ou no título de algum vídeo
   da execução (e não é stopword já);
2. **confirmada** — dos comentários que a contêm, pelo menos
   `CONCENTRACAO_MINIMA` vêm de um único vídeo.

"renault" aparece em 98% dos casos nos comentários do vídeo da Renault: vira
stopword. "trailer" se espalha pelos três vídeos de jogos: fica.

**Execução de um vídeo só não usa isto.** Com um vídeo, toda palavra está 100%
concentrada nele por definição, e o critério apagaria o corpus inteiro. Abaixo de
dois vídeos a função devolve conjunto vazio — e é por isso que ela recebe os
vídeos, e não só os comentários.
"""

import logging
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from app.topicos.texto import PALAVRA, STOPWORDS, limpar

logger = logging.getLogger(__name__)

CONCENTRACAO_MINIMA = 0.85
"""Fração dos comentários com a palavra que precisa vir de um único vídeo.

0,85 e não 1,0 porque marca vaza um pouco: alguém comenta "melhor que o
Renault" no vídeo da Chevrolet, e um punhado de menções cruzadas não faz de
"renault" um assunto. E não 0,5, que pegaria palavra genuinamente compartilhada
por dois de quatro vídeos."""

MINIMO_DE_COMENTARIOS_PARA_JULGAR = 3
"""Abaixo disto a concentração não significa nada.

Uma palavra em dois comentários está "100% concentrada" em um vídeo com metade
da facilidade que uma em duzentos. É o mesmo `min_df` do vetorizador: palavra que
não aparece três vezes não entra no vocabulário de todo modo."""

MINIMO_DE_VIDEOS = 2
"""Com um vídeo só, tudo está concentrado nele. Ver o cabeçalho do módulo."""


@dataclass(frozen=True, slots=True)
class VideoDaExecucao:
    """O que este módulo precisa saber de um vídeo: como ele se chama."""

    id_video: int
    titulo: str
    canal: str


@dataclass(frozen=True, slots=True)
class Candidata:
    """Uma palavra de marca avaliada, com o número que decidiu o caso.

    Guardada inteira (e não só o veredito) porque é o que permite explicar na
    banca por que "renault" saiu e "trailer" ficou, sem refazer a conta.
    """

    palavra: str
    comentarios: int
    concentracao: float
    id_video_dominante: int

    @property
    def e_marca(self) -> bool:
        return (
            self.comentarios >= MINIMO_DE_COMENTARIOS_PARA_JULGAR
            and self.concentracao >= CONCENTRACAO_MINIMA
        )


@dataclass(frozen=True, slots=True)
class ResultadoMarcas:
    """As stopwords de marca da execução, e o que foi avaliado para chegar nelas."""

    palavras: frozenset[str] = frozenset()
    avaliadas: tuple[Candidata, ...] = ()
    motivo: str | None = None

    @property
    def mantidas(self) -> tuple[Candidata, ...]:
        """Candidatas que a medição POUPOU — as que atravessam os vídeos."""
        return tuple(c for c in self.avaliadas if not c.e_marca)


def _dobrar(palavra: str) -> str:
    decomposta = unicodedata.normalize("NFD", palavra)
    return "".join(c for c in decomposta if unicodedata.category(c) != "Mn")


def _palavras_de(texto: str) -> set[str]:
    """Tokens do título/canal, na mesma forma dobrada em que o corpus é contado."""
    return {_dobrar(p) for p in PALAVRA.findall(limpar(texto))}


def candidatas(videos: list[VideoDaExecucao]) -> frozenset[str]:
    """Palavras do nome do canal e do título dos vídeos, menos as já conhecidas.

    Tokens de uma ou duas letras saem: "5G", "A16" e "PS5" já não passariam pelo
    tamanho mínimo do tokenizador, e mantê-los aqui só encheria o log.
    """
    brutas: set[str] = set()
    for video in videos:
        brutas |= _palavras_de(video.canal)
        brutas |= _palavras_de(video.titulo)
    return frozenset(p for p in brutas if len(p) >= 3 and p not in STOPWORDS)


def stopwords_de_marca(
    videos: list[VideoDaExecucao],
    comentarios: list[tuple[int, int, str]],
) -> ResultadoMarcas:
    """As palavras de marca desta execução, confirmadas pela distribuição real.

    `comentarios` é `(id_comentario, id_video, texto ORIGINAL)`.
    """
    if len(videos) < MINIMO_DE_VIDEOS:
        return ResultadoMarcas(
            motivo=(
                f"execucao com {len(videos)} video(s): abaixo de {MINIMO_DE_VIDEOS} toda "
                "palavra esta concentrada num video so e o criterio nao distingue nada"
            )
        )

    possiveis = candidatas(videos)
    if not possiveis:
        return ResultadoMarcas(motivo="nenhuma palavra de canal ou titulo fora das stopwords")

    # Em quantos comentários de CADA vídeo a palavra aparece. Conta por
    # comentário, não por ocorrência: um comentário que repete "renault" cinco
    # vezes não vale por cinco.
    por_palavra: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for _, id_video, texto in comentarios:
        presentes = {_dobrar(p) for p in PALAVRA.findall(limpar(texto))} & possiveis
        for palavra in presentes:
            por_palavra[palavra][id_video] += 1

    avaliadas: list[Candidata] = []
    for palavra, por_video in por_palavra.items():
        total = sum(por_video.values())
        id_dominante, quantos = max(por_video.items(), key=lambda kv: (kv[1], -kv[0]))
        avaliadas.append(
            Candidata(
                palavra=palavra,
                comentarios=total,
                concentracao=quantos / total if total else 0.0,
                id_video_dominante=id_dominante,
            )
        )

    avaliadas.sort(key=lambda c: (-c.comentarios, c.palavra))
    marcas = frozenset(c.palavra for c in avaliadas if c.e_marca)
    return ResultadoMarcas(palavras=marcas, avaliadas=tuple(avaliadas))
