"""A entrada do motor: os agregados de uma execução, já contados.

**O motor não lê banco.** Estas estruturas são o contrato entre quem consulta
(o futuro endpoint, ou o worker de tópicos) e quem raciocina. O motivo é
testabilidade: as regras de insight são exatamente o tipo de código que precisa
ser exercitado em casos-limite — tema com três comentários, variação de meio
ponto percentual, modelo com uma execução só — e montar cada um desses cenários
como linhas de Postgres custaria dez vezes mais que montar um dataclass.

Espelham `frontend/src/app/core/api/dominio.models.ts` de propósito: os nomes de
campo são os das colunas, em português (CLAUDE.md Seção 7), para que a banca
consiga seguir o caminho do DER até a frase na tela sem tradução no meio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.insights.texto import normalizar_palavra_chave


@dataclass(frozen=True, slots=True)
class Distribuicao:
    """Contagem de ANALISES_SENTIMENTO por valor de `sentimento`.

    As frações são propriedades, e não campos, porque um total e três frações
    gravados lado a lado podem divergir — e aí duas regras que consultam campos
    diferentes discordam sobre o mesmo tema. Aqui só as contagens são estado.
    """

    positivo: int = 0
    neutro: int = 0
    negativo: int = 0

    def __post_init__(self) -> None:
        if self.positivo < 0 or self.neutro < 0 or self.negativo < 0:
            raise ValueError("contagem de sentimento nao pode ser negativa")

    @property
    def total(self) -> int:
        return self.positivo + self.neutro + self.negativo

    @property
    def fracao_negativa(self) -> float:
        """0.0 quando não há comentário nenhum — e não divisão por zero.

        Um tema vazio não é "0% negativo" no sentido de bem recebido; ele é
        indeterminado. Quem impede que essa ambiguidade vire afirmação é a
        amostra mínima (`configuracao.py`), não este método: aqui o zero é só
        um valor de retorno seguro.
        """
        return self.negativo / self.total if self.total else 0.0

    @property
    def fracao_positiva(self) -> float:
        return self.positivo / self.total if self.total else 0.0

    @property
    def fracao_neutra(self) -> float:
        return self.neutro / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class TemaAgregado:
    """Uma linha de TEMAS com as contagens dos comentários ligados a ela.

    `palavras_chave` não é enfeite: é por ela que o mesmo assunto é reconhecido
    entre duas coletas (`temas.py`). O `rotulo_tema` NÃO serve para isso — ele
    é gerado por execução e duas rodadas de LDA sobre corpora diferentes
    produzem rótulos diferentes para o mesmo assunto.
    """

    id_tema: int
    rotulo_tema: str
    distribuicao: Distribuicao
    palavras_chave: tuple[str, ...] = ()

    @property
    def chaves_normalizadas(self) -> frozenset[str]:
        """As palavras-chave prontas para comparação entre execuções."""
        return frozenset(
            normalizada
            for palavra in self.palavras_chave
            if (normalizada := normalizar_palavra_chave(palavra))
        )


@dataclass(frozen=True, slots=True)
class VideoAgregado:
    """Uma linha de VIDEOS com as contagens dos comentários daquele vídeo.

    `youtube_video_id` é o que identifica o vídeo ENTRE execuções: `id_video` é
    a chave primária local e nasce de novo a cada coleta (VIDEOS tem
    `id_execucao`), então comparar duas coletas por ele não casaria nada.
    """

    id_video: int
    youtube_video_id: str
    titulo: str
    distribuicao: Distribuicao


@dataclass(frozen=True, slots=True)
class AgregadosExecucao:
    """Tudo o que o motor precisa saber de UMA execução.

    `distribuicao` é o total da execução e vem de fora em vez de ser somado a
    partir de `temas` ou de `videos`: um comentário pode estar em vários temas
    (COMENTARIO_TEMA é N:N) e em nenhum, então nenhuma das duas somas fecha com
    o total. Quem faz a consulta sabe disso; o motor não tem como adivinhar.
    """

    id_execucao: int
    id_modelo: int
    distribuicao: Distribuicao
    temas: tuple[TemaAgregado, ...] = ()
    videos: tuple[VideoAgregado, ...] = ()
    concluido_em: datetime | None = None
