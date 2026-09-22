"""Pré-processamento de texto compartilhado entre treino (`ml/`) e inferência (`backend/`).

Ponto de entrada único: `preparar_texto`. É ela que o pipeline de treino aplica ao
corpus e que o worker de inferência aplica ao comentário que chega — **a mesma
função, o mesmo código**. Se as duas metades pré-processassem diferente, o modelo
receberia em produção um texto que nunca viu no treino (train/serving skew), e a
métrica da banca não valeria para o sistema real.

`VERSAO` entra no `model_card.json` junto dos pesos. O worker de inferência compara
a versão do card com a versão instalada: divergiu, o texto de produção não é mais o
texto do treino, e isso precisa aparecer como erro, não como queda silenciosa de
acurácia.

Regra ao mexer aqui: qualquer mudança que altere a SAÍDA de `preparar_texto` para
um texto que já existia é uma mudança de major/minor — o modelo treinado com a
versão anterior fica desalinhado. Acrescentar emoji ao mapa muda a saída. Corrigir
um typo de comentário, não.
"""

from preprocessamento.emoji import MAPA_EMOJI, converter_emoji, e_emoji
from preprocessamento.texto import (
    SUBSTITUICOES_TIPOGRAFICAS,
    normalizar_espacos,
    normalizar_tipografia,
    preparar_texto,
)

# Mantenha em sincronia com `version` do pyproject.toml.
VERSAO = "1.1.0"

__all__ = [
    "MAPA_EMOJI",
    "SUBSTITUICOES_TIPOGRAFICAS",
    "VERSAO",
    "converter_emoji",
    "e_emoji",
    "normalizar_espacos",
    "normalizar_tipografia",
    "preparar_texto",
]
