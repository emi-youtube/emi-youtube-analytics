"""O que o motor produz: um **fato**, não uma frase.

A separação é o ponto do pacote. Uma regra decide *que* algo é verdade e com que
força; o texto é só uma apresentação disso. Se o motor devolvesse apenas a frase
pronta, a tela não teria como ordenar os achados por relevância, filtrar os que
não têm amostra suficiente, nem montar o link para o tema que originou a
afirmação — teria uma string. Por isso `texto` é o ÚLTIMO campo de `Fato`, e
tudo que decide vem estruturado antes dele.

`valores` é deliberadamente um dicionário de primitivos (e não um campo por
tipo de fato): cada `TipoFato` tem o seu conjunto, o modelo de frase
correspondente sabe quais chaves esperar, e acrescentar um tipo novo não mexe
em nenhuma estrutura existente. O preço é não haver checagem estática das
chaves — pago de propósito, e coberto pelos testes de cada regra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Valor que cabe num fato. É o que o `json.dumps` do endpoint vai ver, então
# nada de datetime, Decimal ou dataclass aqui dentro.
Valor = str | int | float | bool | None


class TipoFato(StrEnum):
    """Os achados que o motor sabe produzir.

    `StrEnum` porque este valor atravessa a API como string e aparece no
    contrato do frontend: `tipo === 'tema_mais_criticado'` do lado do Angular
    tem que comparar com o que o Python serializou, sem tabela de conversão no
    meio.
    """

    # --- de uma execução ---
    TEMA_MAIS_CRITICADO = "tema_mais_criticado"
    TEMA_MELHOR_RECEBIDO = "tema_melhor_recebido"
    VIDEO_MUITO_NEGATIVO = "video_muito_negativo"
    CONCENTRACAO_DAS_CRITICAS = "concentracao_das_criticas"

    # --- da campanha (várias execuções do mesmo modelo) ---
    VARIACAO_DE_SENTIMENTO = "variacao_de_sentimento"
    EVOLUCAO_DO_VIDEO = "evolucao_do_video"


@dataclass(frozen=True, slots=True)
class Amostra:
    """Quantos comentários sustentam a afirmação, e quantos eram exigidos.

    Os dois números viajam juntos porque o segundo é o que torna o primeiro
    interpretável. "42 comentários" não diz nada sozinho; "42 de um mínimo de
    30" diz que a regra foi aplicada e passou. A tela pode mostrar isso como
    nota de rodapé, e a banca pode perguntar de onde saiu o corte — a resposta
    está no próprio fato, não numa constante escondida no código.
    """

    tamanho: int
    minimo_exigido: int

    def __post_init__(self) -> None:
        if self.tamanho < 0 or self.minimo_exigido < 0:
            raise ValueError("amostra nao pode ser negativa")

    @property
    def suficiente(self) -> bool:
        return self.tamanho >= self.minimo_exigido


@dataclass(frozen=True, slots=True)
class Origem:
    """A que linhas do banco o fato se refere — é o que a tela transforma em link.

    Todos os campos são opcionais porque cada tipo de fato aponta para coisas
    diferentes: um fato de tema tem `id_tema`, um de vídeo tem `id_video`, e um
    de campanha não tem nenhum dos dois mas tem `id_execucoes` com as duas
    coletas comparadas. Um campo obrigatório aqui obrigaria a inventar valor
    para os fatos que não o têm, e `id_tema: 0` é pior que ausência.

    `id_execucoes` é uma tupla, e não um par, porque um fato de campanha pode
    vir a comparar mais de duas coletas; a ordem é cronológica.
    """

    id_execucoes: tuple[int, ...] = ()
    id_tema: int | None = None
    id_video: int | None = None
    youtube_video_id: str | None = None


@dataclass(frozen=True, slots=True)
class Fato:
    """Um achado do motor, pronto para a API serializar.

    `texto` vem preenchido pelo modelo de frase (`frases.py`) no momento em que
    o fato é construído, e não é escolhido pela tela: a frase faz parte da
    análise — se a regra mudar, a frase muda junto, num lugar só.
    """

    tipo: TipoFato
    valores: dict[str, Valor] = field(default_factory=dict)
    amostra: Amostra = Amostra(tamanho=0, minimo_exigido=0)
    origem: Origem = Origem()
    texto: str = ""
