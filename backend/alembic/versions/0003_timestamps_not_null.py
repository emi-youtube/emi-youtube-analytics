"""Alinha nullability dos timestamps com server default ao que os models declaram

As colunas abaixo tem DEFAULT now() e nunca deveriam aceitar NULL. A 0001/0002
criaram-nas como nullable, o que fazia `alembic check` acusar divergencia e
poluiria qualquer --autogenerate futuro.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUNAS = [
    ("usuarios", "criado_em"),
    ("modelos_analise", "criado_em"),
    ("analises_sentimento", "processado_em"),
    ("jobs", "criado_em"),
    ("jobs_dlq", "falhou_em"),
    ("tokens_atualizacao", "criado_em"),
]


def upgrade() -> None:
    for tabela, coluna in COLUNAS:
        op.alter_column(
            tabela, coluna, existing_type=sa.DateTime(timezone=True), nullable=False
        )


def downgrade() -> None:
    for tabela, coluna in COLUNAS:
        op.alter_column(
            tabela, coluna, existing_type=sa.DateTime(timezone=True), nullable=True
        )
