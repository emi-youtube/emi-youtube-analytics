"""Classificador lexico (SentiLex-PT02) compartilhado entre `ml/` e `backend/`.

Ponto de entrada unico: `carregar` (le o recurso) e `classificar` (decide o rotulo).
E a **mesma** regra em dois papeis:

- no `ml/`, e a **linha de base** do Capitulo 5 -- o piso que o BERTimbau precisa
  superar para justificar o custo de treinar um modelo;
- no `backend/`, e a **primeira implementacao** do worker de inferencia, enquanto o
  BERTimbau oficial nao existe.

Os dois papeis exigem que a regra seja literalmente a mesma linha de codigo. Se o
experimento e a producao tivessem cada um a sua copia, elas divergiriam, e o numero
do capitulo deixaria de descrever o que a PME ve no painel.

`VERSAO` e do NOSSO classificador (a regra, o parser do recurso), nao do SentiLex.
O recurso e identificado pelo `sha256` que `Lexico` carrega junto -- e esse hash que
prova, na banca, que o numero do capitulo saiu deste arquivo e nao de outro.

Regra ao mexer aqui: qualquer mudanca que altere o ROTULO de um texto que ja existia
muda tanto o piso do capitulo quanto a classificacao de producao. Sobe minor/major,
e a linha correspondente em VERSOES_MODELO passa a ser outra.
"""

from lexico.sentilex import (
    CAMPO_COMPLEMENTO,
    CAMPO_SUJEITO,
    NEGATIVO,
    NEUTRO,
    POLARIDADES_VALIDAS,
    POSITIVO,
    Lexico,
    Previsao,
    carregar,
    classificar,
    classificar_muitos,
    normalizar_chave,
    tokenizar,
)

# Mantenha em sincronia com `version` do pyproject.toml.
VERSAO = "1.0.0"

__all__ = [
    "CAMPO_COMPLEMENTO",
    "CAMPO_SUJEITO",
    "NEGATIVO",
    "NEUTRO",
    "POLARIDADES_VALIDAS",
    "POSITIVO",
    "VERSAO",
    "Lexico",
    "Previsao",
    "carregar",
    "classificar",
    "classificar_muitos",
    "normalizar_chave",
    "tokenizar",
]
