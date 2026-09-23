"""O `model_card.json` — o contrato entre o `ml/` e o `backend/`.

As duas metades do repositório não se importam (CLAUDE.md Seção 3): elas conversam
por artefato. O artefato é a pasta do modelo, e este arquivo é o que diz ao worker de
inferência **como** usar os pesos que estão ao lado dele.

Três campos existem por causa de bugs que eles evitam:

- **`id2label`** — a ordem dos rótulos sai daqui, nunca do código (regra 5). Se o
  backend hardcodar `["positivo", "negativo", "neutro"]` e um treino futuro trocar a
  ordem, o modelo prevê "negativo" e o banco grava "neutro": erro silencioso, que
  nenhum teste de API pega e que só aparece quando a PME reclama do dashboard;
- **`versao_preprocessamento`** — o worker compara com a versão instalada do pacote
  `preprocessamento` e **recusa o modelo** se divergir. Divergência significa que o
  texto de produção não é mais o texto do treino, e isso precisa ser erro, não queda
  silenciosa de acurácia;
- **`max_length`** — truncar em 128 no treino e em 512 na inferência daria ao modelo
  uma entrada com cauda que ele nunca viu.

O resto (hiperparâmetros, semente, métricas, data, tamanho dos conjuntos) é
reprodutibilidade: é o que permite a alguém refazer este treino e chegar ao mesmo
lugar, que é o que a banca pede quando pergunta "como vocês chegaram nesse número?".

Sem `torch` aqui: montar o cartão é manipulação de dicionário, e testar isso não pode
exigir GPU nem meio giga de peso.
"""

from datetime import UTC, datetime
from typing import Any

# Versão do FORMATO do cartão, não do modelo. Se um campo obrigatório mudar de nome
# ou de sentido, isto sobe e o backend consegue recusar um cartão que não entende.
VERSAO_CARTAO = "1.0"

CAMPOS_OBRIGATORIOS = (
    "id2label",
    "label2id",
    "max_length",
    "versao",
    "versao_preprocessamento",
    "modelo_base",
)


def montar_cartao(
    *,
    classes: tuple[str, ...],
    max_length: int,
    versao: str,
    versao_preprocessamento: str,
    modelo_base: str,
    hiperparametros: dict[str, Any],
    semente: int,
    metricas_validacao: dict[str, Any],
    dados: dict[str, Any],
    observacoes: str = "",
) -> dict[str, Any]:
    """Monta o cartão. Argumentos por nome de propósito: trocar `versao` com
    `versao_preprocessamento` por posição seria um erro caro e mudo.

    `id2label` tem chave string porque JSON não tem chave inteira — quem lê precisa
    fazer `int(chave)`, e é isso que o backend faz.
    """
    return {
        "versao_cartao": VERSAO_CARTAO,
        "versao": versao,
        "modelo_base": modelo_base,
        "id2label": {str(indice): classe for indice, classe in enumerate(classes)},
        "label2id": {classe: indice for indice, classe in enumerate(classes)},
        "max_length": max_length,
        "versao_preprocessamento": versao_preprocessamento,
        "semente": semente,
        "hiperparametros": hiperparametros,
        "dados": dados,
        "metricas_validacao": metricas_validacao,
        "treinado_em_utc": datetime.now(UTC).isoformat(),
        "observacoes": observacoes,
    }


def validar_cartao(cartao: dict[str, Any]) -> None:
    """Confere o cartão antes de ele sair junto dos pesos.

    É barato aqui e caro depois: um cartão sem `id2label` só falha no worker, em
    produção, no meio de uma execução.
    """
    faltando = [campo for campo in CAMPOS_OBRIGATORIOS if campo not in cartao]
    if faltando:
        raise ValueError(f"model_card.json sem campo(s) obrigatorio(s): {', '.join(faltando)}")

    id2label = cartao["id2label"]
    label2id = cartao["label2id"]
    if {int(chave) for chave in id2label} != set(range(len(id2label))):
        raise ValueError(f"id2label precisa cobrir 0..n-1 sem buraco, veio {sorted(id2label)}")
    if {classe: int(indice) for classe, indice in label2id.items()} != {
        classe: int(chave) for chave, classe in id2label.items()
    }:
        raise ValueError("label2id e id2label discordam entre si")

    if not isinstance(cartao["max_length"], int) or cartao["max_length"] < 1:
        raise ValueError(f"max_length invalido: {cartao['max_length']!r}")
