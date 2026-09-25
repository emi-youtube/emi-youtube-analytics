"""Primeira implementação do `Classificador`: SentiLex-PT02 + soma de polaridade.

Ela existe para o painel ter rótulo antes do BERTimbau existir. Não é um modelo
provisório mal-feito: é o **piso do Capítulo 5** rodando em produção, a mesma regra,
o mesmo código (pacote `lexico`, compartilhado com o `ml/`). Quando o BERTimbau
estiver treinado, esta classe continua no repositório — é o número que ele precisa
superar, e a comparação só vale se o piso for exatamente este.

O que esta camada acrescenta ao pacote `lexico`, que é função pura:

1. **carrega o recurso uma vez**, na inicialização do worker, e confere o `sha256`;
2. **traduz `Previsao` em `Classificacao`**, montando a justificativa que a tela
   mostra em "Por que foi classificado assim";
3. **declara a identidade da versão** para VERSOES_MODELO, com a proveniência do
   arquivo que foi usado.

Por que o `sha256` é conferido, e não só registrado: o arquivo do SentiLex está fora
do git (dado de terceiro, 6,9 MB). Se ele for baixado de outro espelho, truncado pelo
download ou substituído pelo `lem` no lugar do `flex`, a classificação de produção
muda em silêncio — e o número do Capítulo 5 passa a descrever um recurso que não é
mais o que está rodando. O `ml/lexico/README.md` já previa esse tratamento para
quando o léxico deixasse de ser só dado de experimento.
"""

import logging
from pathlib import Path

from lexico import VERSAO as VERSAO_LEXICO
from lexico import Lexico, carregar, classificar
from preprocessamento import VERSAO as VERSAO_PREPROCESSAMENTO

from app.inferencia.base import (
    Classificacao,
    Classificador,
    ClassificadorIndisponivel,
    DescritorVersao,
)

logger = logging.getLogger(__name__)

NOME_MODELO = "lexico-sentilex"

# sha256 do `SentiLex-flex-PT02.txt` registrado em ml/lexico/metadados_lexico.json —
# o mesmo arquivo com que a linha de base do Capítulo 5 foi calculada. Trocar de
# arquivo é trocar de classificador: a versão sobe e esta constante muda junto.
SHA256_ESPERADO = "88ab7389bfe6f4a2b489a4a53c42306691796bc2fef9d4c2a26790dd927ba85c"

COMO_OBTER = (
    "Baixe o recurso (CC-BY 4.0, ver ml/lexico/README.md) para ml/lexico/dados/ ou "
    "aponte SENTILEX_PATH no .env para onde ele ja esta. A URL do espelho esta no "
    "README; o arquivo e o SentiLex-flex-PT02.txt (flex, nao lem)."
)

# Teto de palavras citadas na justificativa. Um comentário longo pode casar dezenas
# de termos, e a tela mostra a explicação junto do comentário — a lista inteira
# deixaria de explicar. As palavras vêm na ordem do texto, então o corte é do fim.
MAX_TERMOS_NA_JUSTIFICATIVA = 8

SEM_COBERTURA = "nenhuma palavra do lexico foi reconhecida neste comentario"


def _formatar_termos(termos: tuple[tuple[str, int], ...]) -> str:
    """`(("ótimo", 1), ("caro", -1))` -> `"ótimo (+1), caro (-1)"`.

    O sinal vem explícito (`+1`, e não `1`) porque a justificativa é lida por humano:
    numa lista de oito termos, o `+` é o que deixa ver de que lado cada palavra puxou.
    """
    visiveis = termos[:MAX_TERMOS_NA_JUSTIFICATIVA]
    texto = ", ".join(f"{palavra} ({polaridade:+d})" for palavra, polaridade in visiveis)
    restantes = len(termos) - len(visiveis)
    if restantes:
        texto += f" e mais {restantes}"
    return texto


class ClassificadorLexico(Classificador):
    """SentiLex-PT02 carregado em memória, pronto para classificar.

    O `Lexico` (43 mil entradas utilizáveis) é carregado UMA vez e compartilhado por
    todas as execuções do processo: dentro do escopo do projeto (500 a 5.000
    comentários), a classificação em si é soma de inteiros — o custo todo está em ler
    o arquivo.
    """

    def __init__(self, lexico: Lexico) -> None:
        self._lexico = lexico

    @classmethod
    def de_arquivo(cls, caminho: Path) -> "ClassificadorLexico":
        """Carrega o recurso e confere o hash. Falha AQUI, não durante uma execução.

        As três falhas possíveis dão mensagens diferentes de propósito: arquivo
        ausente, arquivo ilegível e arquivo diferente do medido são problemas
        diferentes, e quem está subindo o worker precisa saber qual é o seu.
        """
        if not caminho.is_file():
            raise ClassificadorIndisponivel(
                f"arquivo do SentiLex nao encontrado em {caminho}\n"
                f"Ele nao e versionado (dado de terceiro, 6,9 MB). {COMO_OBTER}"
            )

        try:
            lexico = carregar(caminho)
        except (OSError, UnicodeDecodeError) as erro:
            raise ClassificadorIndisponivel(
                f"arquivo do SentiLex em {caminho} nao pode ser lido: {erro}\n"
                f"Esperado texto UTF-8 no formato do SentiLex-PT02. {COMO_OBTER}"
            ) from erro

        if lexico.sha256 != SHA256_ESPERADO:
            raise ClassificadorIndisponivel(
                f"arquivo do SentiLex em {caminho} nao e o que foi medido:\n"
                f"  esperado sha256 {SHA256_ESPERADO}\n"
                f"  encontrado      {lexico.sha256}\n"
                "Classificar com outro recurso muda o rotulo em silencio e desalinha a "
                f"linha de base do Capitulo 5 (ml/lexico/metadados_lexico.json). {COMO_OBTER}"
            )

        logger.info(
            "lexico carregado arquivo=%s entradas_utilizaveis=%s de %s lidas sha256=%s",
            lexico.arquivo,
            len(lexico),
            lexico.entradas_lidas,
            lexico.sha256[:12],
        )
        return cls(lexico)

    @property
    def descritor(self) -> DescritorVersao:
        return DescritorVersao(
            nome_modelo=NOME_MODELO,
            versao=VERSAO_LEXICO,
            proveniencia={
                "metodo": "soma de polaridade sobre o SentiLex-PT02",
                "recurso": {
                    "nome": "SentiLex-PT02",
                    "arquivo": self._lexico.arquivo,
                    "sha256": self._lexico.sha256,
                    "licenca": "CC-BY 4.0",
                    "citacao": "Silva, Carvalho e Sarmento (2012), PROPOR",
                    "entradas_lidas": self._lexico.entradas_lidas,
                    "entradas_utilizaveis": len(self._lexico),
                    "descartes": self._lexico.descartes,
                },
                "versao_preprocessamento": VERSAO_PREPROCESSAMENTO,
                # Dito aqui porque é o que a banca vai perguntar ao ver esta linha em
                # VERSOES_MODELO: por que o sistema roda o piso do capítulo.
                "papel": (
                    "linha de base (piso) do Capitulo 5, em producao enquanto o "
                    "BERTimbau oficial nao existe"
                ),
            },
        )

    @property
    def versao_preprocessamento(self) -> str:
        # O léxico não é treinado, então nada nele "quebra" com outra versão do
        # pré-processamento. O portão vale de todo modo: o número do Capítulo 5 foi
        # medido sobre o `preparar_texto` desta versão, inclusive a conversão de emoji
        # que faz o léxico enxergar o emoji de coração como "amei". Com outra versão,
        # o piso publicado deixa de ser o piso que está rodando — e isso é para
        # aparecer, não para passar.
        return VERSAO_PREPROCESSAMENTO

    def classificar(self, texto_modelo: str) -> Classificacao:
        """Soma as polaridades e devolve o sinal, com as palavras que decidiram.

        `neutro` sai por dois caminhos, e a justificativa os distingue: o léxico não
        achou nada, ou achou e os lados se anularam. São fracassos diferentes, e é o
        que o usuário precisa ler antes de confiar no rótulo.
        """
        previsao = classificar(texto_modelo, self._lexico)
        justificativa = _formatar_termos(previsao.termos) if previsao.cobriu else SEM_COBERTURA
        return Classificacao(sentimento=previsao.rotulo, justificativa=justificativa)
