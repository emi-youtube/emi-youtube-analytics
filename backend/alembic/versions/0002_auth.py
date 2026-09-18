"""Autenticacao UC01: tokens_atualizacao (refresh revogavel) e tentativas_login (bloqueio)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tokens_atualizacao",
        sa.Column("id_token", sa.Integer(), primary_key=True),
        sa.Column(
            "id_usuario",
            sa.Integer(),
            sa.ForeignKey("usuarios.id_usuario", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revogado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_tokens_atualizacao_token_hash"),
    )

    op.create_table(
        "tentativas_login",
        sa.Column("id_tentativa", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "tentado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_tentativas_login_email_tentado_em", "tentativas_login", ["email", "tentado_em"]
    )


def downgrade() -> None:
    op.drop_index("ix_tentativas_login_email_tentado_em", table_name="tentativas_login")
    op.drop_table("tentativas_login")
    op.drop_table("tokens_atualizacao")
