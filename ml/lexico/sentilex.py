"""Classificador léxico: SentiLex-PT02 + soma de polaridade. O piso do Capítulo 5.

Funções **puras**: recebem texto, devolvem rótulo. Nada de banco, nada de planilha,
nada de `ml.config` — o que lê o banco e grava o CSV mora em `classificar_teste.py`.
A separação não é só estética: é o que permite que este módulo seja importado pelo
worker de inferência como *fallback* sem arrastar o `ml/` inteiro para dentro do
`backend/` (ver "Promoção para o pacote compartilhado" no README desta pasta).

**O que este classificador é.** O TC2 (Seção 3.8) cita o SentiLex-PT como a
abordagem léxica clássica para o português. Aqui ele existe como **linha de base**:
o número que o BERTimbau precisa superar para justificar o custo de treinar um
modelo. Não é um concorrente ajustado — é o piso. Por isso a regra é a mais simples
que existe: soma as polaridades das palavras conhecidas e olha o sinal.

Sem negação, sem intensificador, sem janela de escopo, sem desambiguação por PoS.
Cada uma dessas heurísticas melhoraria o número e tornaria a comparação menos
honesta: o piso tem que ser o piso, não uma segunda tentativa de modelo.

**Entrada: `texto_modelo`**, o mesmo `preparar_texto` que alimenta o BERTimbau
(CLAUDE.md Seção 3). É o que isola o método na comparação — se o léxico lesse o
texto original e o BERTimbau o pré-processado, a diferença entre eles misturaria
"método" com "pré-processamento" e o Capítulo 5 não poderia atribuir o ganho a
nenhum dos dois. Efeito colateral documentado: a conversão de emoji faz o léxico
enxergar 😂 como "risos", palavra que ele conhece.

Referência do recurso:
  Silva, M. J.; Carvalho, P.; Sarmento, L. (2012). Building a Sentiment Lexicon for
  Social Judgement Mining. PROPOR 2012, LNCS/LNAI.
  SentiLex-PT02 — CC-BY 4.0. Ver `ml/lexico/README.md` para proveniência e download.
"""

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

# Rótulos do projeto (CLAUDE.md Seção 4). Repetidos aqui em vez de importados de
# `ml.config` de propósito: este módulo não pode depender do `ml/` para poder virar
# fallback do worker. O teste trava os dois valores em sincronia.
POSITIVO, NEGATIVO, NEUTRO = "positivo", "negativo", "neutro"

# Polaridades que o SentiLex declara. Qualquer outro valor é erro de digitação do
# recurso publicado (existem quatro: `POL:N0=7`, `=8`, `=-2`, `=-3`), e entrada com
# erro é descartada, não corrigida por palpite.
POLARIDADES_VALIDAS = frozenset({-1, 0, 1})

# Palavra = sequência de letras, aceitando hífen interno ("à-vontade", "bem-vindo").
# Dígito e pontuação não entram: o léxico não tem nenhuma entrada com eles.
TOKEN = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)

# O SentiLex não declara "a polaridade da palavra": declara a polaridade que a
# palavra confere a um ALVO HUMANO, por posição sintática. `POL:N0` é o sujeito e
# `POL:N1` o complemento — "abandonar" é -1 para quem abandona e 0 para quem é
# abandonado. O recurso foi construído para julgamento social sobre pessoas, e é
# essa a diferença entre ele e a nossa tarefa, que julga um anúncio.
#
# A regra: vale o `POL:N0`; quando ele é ZERO e existe `POL:N1` diferente de zero,
# vale o `POL:N1`. Nunca o contrário — polaridade declarada no sujeito não é
# sobrescrita.
#
# É a cláusula que faz o piso enxergar os verbos de julgamento. "adorar", "amar",
# "odiar", "gostar" e "aplaudir" trazem `POL:N0=0` com `POL:N1=±1`: o recurso diz
# que quem adora não é julgado, mas quem é adorado sai bem. Num comentário de
# anúncio o alvo é o produto, que ocupa justamente essa posição. Medido no conjunto
# de teste: 3.927 formas flexionadas mudam de polaridade e 22 dos 334 comentários
# mudam de rótulo, puxados por "amei" (7), "gostei" (3), "amo" (3) e "adorei".
# Sem a cláusula, "amei o comercial" some do léxico — e um piso que não vê "amei"
# não mede o método, mede a leitura errada do recurso.
CAMPO_SUJEITO = "POL:N0"
CAMPO_COMPLEMENTO = "POL:N1"


@dataclass(frozen=True)
class Lexico:
    """O SentiLex carregado: da chave normalizada para a polaridade.

    `descartes` é parte do resultado, não um detalhe de log. O Capítulo 5 precisa
    poder dizer quantas entradas do recurso publicado a regra simples realmente
    consegue usar — uma expressão idiomática de quatro palavras está no léxico e é
    invisível para um casamento palavra a palavra.
    """

    polaridades: dict[str, int]
    arquivo: str
    sha256: str
    entradas_lidas: int
    entradas_por_complemento: int = 0
    descartes: dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.polaridades)

    def polaridade(self, palavra: str) -> int | None:
        """Polaridade de uma palavra solta, ou `None` se o léxico não a conhece."""
        return self.polaridades.get(normalizar_chave(palavra))


@dataclass(frozen=True)
class Previsao:
    """O que a regra decidiu sobre um texto, com o rastro de como decidiu.

    `termos` existe para a banca: dá para abrir qualquer classificação e mostrar
    exatamente quais palavras a produziram, que é a única vantagem real que o léxico
    tem sobre o BERTimbau.
    """

    rotulo: str
    escore: int
    termos: tuple[tuple[str, int], ...]

    @property
    def positivos(self) -> int:
        return sum(1 for _, polaridade in self.termos if polaridade > 0)

    @property
    def negativos(self) -> int:
        return sum(1 for _, polaridade in self.termos if polaridade < 0)

    @property
    def cobriu(self) -> bool:
        """O léxico reconheceu alguma palavra do texto?

        Distingue os dois caminhos que levam a `neutro`: "não achei nada" e "achei e
        deu empate". Os dois viram o mesmo rótulo — a regra é o sinal da soma —, mas
        são fracassos diferentes e o Capítulo 5 reporta os dois separados.
        """
        return bool(self.termos)


def normalizar_chave(palavra: str) -> str:
    """Chave de busca: minúscula, **com acento**.

    Tirar o acento dos dois lados pareceria a escolha generosa — comentário de
    YouTube escreve "otimo" e "horrivel" sem acento, e casar mesmo assim daria mais
    cobertura ao piso. **Foi medido no conjunto de teste, e a conta não fecha:**
    ignorar acento sobe de 413 para 446 palavras casadas, e desses 33 ganhos, 17 são
    a conjunção **"mas" casando com "más"** (feminino plural de "mau", polaridade
    -1). Isto é, a palavra que o manual de rotulagem usa como marca de contraste
    injetaria -1 em quase toda frase com "mas". Os ganhos legítimos foram quatro
    ("otima", "fantastico", "pessima", "horrivel"). Trocar quatro acertos por
    dezessete erros sistemáticos não é generosidade com o piso, é ruído.

    O mesmo vale para "seria"/"séria", "vila"/"vilã", "manhã"/"manha", "peço"/"peco"
    e "dúvida"/"duvida", todos presentes no conjunto de teste.

    O acento que o comentarista não digitou continua sendo uma limitação do método
    léxico — e é isso que o Capítulo 5 tem que dizer, em vez de esconder o problema
    numa normalização que cria outro maior.

    >>> normalizar_chave("Ótimo")
    'ótimo'
    >>> normalizar_chave("À-Vontade")
    'à-vontade'
    """
    return unicodedata.normalize("NFC", palavra.casefold())


def _ler_entradas(texto: str) -> Iterator[tuple[str, dict[str, str]]]:
    """Quebra cada linha do SentiLex em (grafia, campos).

    Os dois arquivos do recurso entram aqui:

        lem:   abafado.PoS=Adj;TG=HUM:N0;POL:N0=-1;ANOT=JALC
        flex:  abafada,abafado.PoS=Adj;FLEX=fs;TG=HUM:N0;POL:N0=-1;ANOT=JALC

    A diferença é só a grafia: no `flex` vem "forma,lema" e a forma flexionada é o
    que interessa. O separador é o PRIMEIRO ponto seguido de `PoS=` — partir no
    primeiro ponto qualquer quebraria "dr." e nomes com abreviação.
    """
    for linha in texto.splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#"):
            continue
        posicao = limpa.find(".PoS=")
        if posicao == -1:
            continue
        grafia = limpa[:posicao]
        if "," in grafia:  # arquivo flex: "forma,lema"
            grafia = grafia.split(",", 1)[0]

        campos: dict[str, str] = {}
        for pedaco in limpa[posicao + 1 :].split(";"):
            if "=" in pedaco:
                chave, valor = pedaco.split("=", 1)
                campos[chave.strip()] = valor.strip()
        yield grafia.strip(), campos


def _valor(campos: dict[str, str], campo: str) -> int | None:
    """Um campo de polaridade como inteiro, ou `None` se ausente ou fora da escala."""
    if campo not in campos:
        return None
    try:
        valor = int(campos[campo])
    except ValueError:
        return None
    return valor if valor in POLARIDADES_VALIDAS else None


def _polaridade_declarada(campos: dict[str, str]) -> tuple[int | None, bool]:
    """Polaridade da entrada e se ela veio do complemento (ver `CAMPO_SUJEITO`).

    `None` quando a entrada não declara polaridade utilizável — o caso dos quatro
    erros de digitação do recurso publicado.
    """
    sujeito = _valor(campos, CAMPO_SUJEITO)
    complemento = _valor(campos, CAMPO_COMPLEMENTO)

    if sujeito:  # declarou -1 ou 1 no sujeito: é essa que vale
        return sujeito, False
    if complemento:  # sujeito neutro ou ausente, complemento decide
        return complemento, True
    return sujeito, False


def carregar(caminho: Path) -> Lexico:
    """Lê um arquivo do SentiLex-PT02 (`lem` ou `flex`) e indexa por chave normalizada.

    O que é descartado, e por quê:

    - **multipalavra**: as 666 expressões idiomáticas ("abrir o coração") não casam
      com uma busca palavra a palavra. Entram na contagem para o Capítulo 5 poder
      dizer que a regra simples ignora 8% do recurso;
    - **polaridade inválida**: os quatro erros de digitação do recurso publicado
      (`=7`, `=8`, `=-2`, `=-3`). Somar 8 daria a uma palavra o peso de oito;
    - **colisão**: a mesma grafia aparecendo duas vezes com polaridades diferentes —
      acontece quando o recurso traz o mesmo lema em duas classes gramaticais. A
      chave sai do índice inteira: chutar qual das duas vale embutiria no piso uma
      desambiguação que a regra simples não faz.
    """
    bruto = caminho.read_bytes()
    texto = bruto.decode("utf-8", errors="strict")

    polaridades: dict[str, int] = {}
    conflitantes: set[str] = set()
    lidas = 0
    multipalavra = 0
    invalidas = 0
    por_complemento = 0

    for grafia, campos in _ler_entradas(texto):
        lidas += 1
        if " " in grafia:
            multipalavra += 1
            continue
        polaridade, do_complemento = _polaridade_declarada(campos)
        if polaridade is None:
            invalidas += 1
            continue
        por_complemento += do_complemento

        chave = normalizar_chave(grafia)
        anterior = polaridades.get(chave)
        if anterior is not None and anterior != polaridade:
            conflitantes.add(chave)
            continue
        polaridades[chave] = polaridade

    for chave in conflitantes:
        polaridades.pop(chave, None)

    return Lexico(
        polaridades=polaridades,
        arquivo=caminho.name,
        sha256=hashlib.sha256(bruto).hexdigest(),
        entradas_lidas=lidas,
        entradas_por_complemento=por_complemento,
        descartes={
            "multipalavra": multipalavra,
            "polaridade_invalida": invalidas,
            "colisao_de_chave": len(conflitantes),
        },
    )


def tokenizar(texto: str) -> list[str]:
    """Palavras do texto, na ordem, sem pontuação e sem número.

    >>> tokenizar("Adorei!! O produto e otimo, serio :)")
    ['Adorei', 'O', 'produto', 'e', 'otimo', 'serio']
    """
    return TOKEN.findall(texto)


def classificar(texto: str, lexico: Lexico) -> Previsao:
    """Soma as polaridades das palavras conhecidas e devolve o sinal.

        escore > 0  -> positivo
        escore < 0  -> negativo
        escore = 0  -> neutro

    O zero cobre dois casos de propósito: o texto em que o léxico não achou nada e o
    texto em que os dois lados se anularam. É a regra mínima; `Previsao.cobriu`
    separa os dois na hora de relatar.

    A mesma palavra conta quantas vezes aparecer. "lixo lixo lixo" é mais negativo
    que "lixo" para a soma — não porque isso seja verdade, mas porque tirar a
    repetição já seria uma heurística, e o piso não tem nenhuma.

    >>> lexico = Lexico({"otimo": 1, "lixo": -1}, "teste", "", 2)
    >>> classificar("produto otimo", lexico).rotulo
    'positivo'
    >>> classificar("otimo produto, mas o suporte e um lixo", lexico).rotulo
    'neutro'
    """
    termos: list[tuple[str, int]] = []
    for palavra in tokenizar(texto):
        polaridade = lexico.polaridades.get(normalizar_chave(palavra))
        if polaridade is not None:
            termos.append((palavra, polaridade))

    escore = sum(polaridade for _, polaridade in termos)
    if escore > 0:
        rotulo = POSITIVO
    elif escore < 0:
        rotulo = NEGATIVO
    else:
        rotulo = NEUTRO
    return Previsao(rotulo=rotulo, escore=escore, termos=tuple(termos))


def classificar_muitos(textos: Iterable[str], lexico: Lexico) -> list[Previsao]:
    """`classificar` em lote. Existe para o chamador não precisar repetir o laço."""
    return [classificar(texto, lexico) for texto in textos]
