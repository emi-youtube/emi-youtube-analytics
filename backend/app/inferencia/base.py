"""A interface do classificador — a costura por onde o BERTimbau vai entrar.

Hoje existe uma implementação (`lexico.ClassificadorLexico`, o SentiLex). Quando o
BERTimbau oficial estiver treinado, a troca tem que ser **só de implementação**: o
worker de inferência não sabe qual das duas está em pé, não monta lote de tensor, não
lê `model_card.json` e não conhece `id2label`. Ele pede um rótulo para um texto e
grava o que voltar.

Por isso três coisas moram aqui, e não no worker:

- **o pré-processamento é do worker, não da implementação.** `preparar_texto` é
  aplicado UMA vez, no worker, antes de chamar `classificar`. Se cada implementação
  aplicasse o seu, a léxica e a BERTimbau poderiam divergir — e a comparação do
  Capítulo 5 mede método, não pré-processamento (CLAUDE.md Seção 3);
- **o portão da versão do pré-processamento** (`validar`). A regra 5 do CLAUDE.md
  manda o worker RECUSAR o modelo quando a versão do `model_card.json` divergir da
  instalada. O portão é o mesmo para as duas implementações: cada uma declara a
  versão com que foi medida, e quem não bate não roda. Para o BERTimbau é
  train/serving skew; para o léxico é o piso do capítulo deixando de descrever a
  produção — os dois precisam ser erro alto, não queda silenciosa;
- **o descritor da versão** (`DescritorVersao`). Toda análise aponta para a linha de
  VERSOES_MODELO que a produziu. Quem sabe se chama "lexico-sentilex 1.0.0" ou
  "bertimbau-emi 1.0.0" é a implementação.

O que NÃO está aqui: `confianca`. A coluna não existe no schema e entra em outro card.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from preprocessamento import VERSAO as VERSAO_PREPROCESSAMENTO_INSTALADA

# Os três rótulos do CHECK de ANALISES_SENTIMENTO (CLAUDE.md Seção 4). O worker
# confere o que a implementação devolveu contra este conjunto ANTES de gravar: um
# rótulo fora dele viraria IntegrityError no meio do lote, e a mensagem do banco não
# diz qual implementação errou.
SENTIMENTOS_VALIDOS = frozenset({"positivo", "negativo", "neutro"})


class ClassificadorIndisponivel(Exception):
    """A implementação não pode ser usada: recurso ausente, corrompido ou incompatível.

    Levantada na INICIALIZAÇÃO, não no meio de uma execução — é a diferença entre o
    worker se recusar a subir com uma mensagem que diz o que fazer e uma execução
    morrer pela metade em produção. A mensagem tem que conter o caminho esperado.
    """


@dataclass(frozen=True)
class DescritorVersao:
    """Identidade da versão que produziu uma análise (VERSOES_MODELO).

    `proveniencia` é o que prova, na banca, que o rótulo saiu deste artefato e não de
    outro: para o léxico é o sha256 do arquivo do SentiLex; para o BERTimbau será o
    conteúdo relevante do `model_card.json`. Vai para `metricas_avaliacao` sob a
    chave `proveniencia` — a avaliação do Capítulo 5 entra ao lado, quando o gabarito
    humano existir (CLAUDE.md regra 6: nunca contra rótulo da Gemini).
    """

    nome_modelo: str
    versao: str
    proveniencia: dict[str, Any]


@dataclass(frozen=True)
class Classificacao:
    """O rótulo e o porquê dele.

    `justificativa` é o que a tela mostra em "Por que foi classificado assim". No
    léxico são as palavras que decidiram o rótulo — a única vantagem real que ele tem
    sobre o BERTimbau. `None` é permitido: uma implementação pode não ter como
    explicar, e a coluna é nula.
    """

    sentimento: str
    justificativa: str | None = None


class Classificador(ABC):
    """Contrato que o worker de inferência consome.

    Síncrono de propósito: classificar é CPU (soma de polaridade hoje, matriz de peso
    amanhã), não espera de rede. `async def` aqui só daria a impressão de que o laço
    de eventos continua livre enquanto o BERTimbau ocupa o processador.
    """

    @property
    @abstractmethod
    def descritor(self) -> DescritorVersao:
        """Identidade desta versão, para VERSOES_MODELO."""

    @property
    @abstractmethod
    def versao_preprocessamento(self) -> str:
        """Versão do pacote `preprocessamento` com que esta versão foi medida/treinada."""

    @abstractmethod
    def classificar(self, texto_modelo: str) -> Classificacao:
        """Rotula um texto JÁ pré-processado (`preparar_texto` é do worker)."""

    def validar(self) -> None:
        """Portão do CLAUDE.md regra 5, rodado na inicialização do worker.

        Não é sobrescrito pelas implementações: o portão precisa ser o mesmo para
        todas, senão uma delas o afrouxa sem ninguém notar.
        """
        if self.versao_preprocessamento != VERSAO_PREPROCESSAMENTO_INSTALADA:
            raise ClassificadorIndisponivel(
                f"{self.descritor.nome_modelo} {self.descritor.versao} foi medido com o "
                f"preprocessamento {self.versao_preprocessamento}, mas o instalado e o "
                f"{VERSAO_PREPROCESSAMENTO_INSTALADA}. O texto que chegaria ao classificador "
                "nao e mais o texto com que ele foi medido. Reinstale a versao correta "
                "(pip install -e ./preprocessamento) ou publique uma versao nova do modelo."
            )
