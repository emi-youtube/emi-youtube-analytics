"""O filtro de posse: o ÚNICO lugar que diz quem enxerga o quê (ADR-011).

Modelos, execuções, resultados e o painel pertencem à EMPRESA. Toda consulta que
alcança esses recursos chega a MODELOS_ANALISE e filtra por esta expressão — a
execução não guarda empresa nem usuário, o dono é o dono do modelo.

Está num módulo próprio, e é chamada como `escopo.da_empresa(...)` e não importada
por nome, para que o teste de mutação (`tests/test_isolamento_empresa.py`) consiga
trocá-la por "sem filtro" e provar que a suíte percebe o vazamento.
"""

from sqlalchemy import ColumnElement

from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario


def da_empresa(usuario: Usuario) -> ColumnElement[bool]:
    """Condição de posse: o modelo é da empresa de quem está autenticado."""
    return ModeloAnalise.id_empresa == usuario.id_empresa
