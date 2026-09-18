"""Indice parcial unico: no maximo uma execucao ativa (pendente/processando) por modelo

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_ATIVOS = "status IN ('pendente', 'processando')"


def upgrade() -> None:
    # A verificacao no servico de execucao da a mensagem de erro; este indice e
    # quem impede de fato duas execucoes ativas do mesmo modelo quando dois POST
    # chegam ao mesmo tempo e passam os dois pela verificacao.
    op.create_index(
        "uq_execucoes_ativa_por_modelo",
        "execucoes",
        ["id_modelo"],
        unique=True,
        postgresql_where=sa.text(STATUS_ATIVOS),
    )


def downgrade() -> None:
    op.drop_index("uq_execucoes_ativa_por_modelo", table_name="execucoes")
