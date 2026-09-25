"""VERSOES_MODELO ganha UNIQUE (nome_modelo, versao)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-24

O worker de inferencia resolve a linha da versao na primeira vez que aquele
classificador roda (app/inferencia/versao.py): busca por (nome_modelo, versao) e
insere se nao existir. Sem esta restricao, dois workers subindo ao mesmo tempo com a
mesma versao criam DUAS linhas, e as analises da mesma implementacao passam a apontar
para id_versao diferentes -- o painel mostraria dois classificadores onde so existe
um, e a metrica do Capitulo 5 sairia particionada entre eles.

A restricao tambem afirma o que a tabela sempre quis dizer: uma versao de um modelo e
uma coisa so. "bertimbau-emi 1.0.0" nao pode ser duas linhas com metricas diferentes;
treino novo e versao nova.

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_versoes_modelo_nome_versao", "versoes_modelo", ["nome_modelo", "versao"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_versoes_modelo_nome_versao", "versoes_modelo", type_="unique")
