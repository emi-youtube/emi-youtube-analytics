"""tentativas_login passa a gravar email_hash (SHA-256) no lugar do e-mail em texto plano

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_tentativas_login_email_tentado_em", table_name="tentativas_login")
    op.add_column("tentativas_login", sa.Column("email_hash", sa.String(64), nullable=True))
    # Converte as linhas existentes sem perder bloqueio em curso. O sha256() do
    # Postgres sobre o UTF-8 do texto dá exatamente o mesmo hexdigest que o
    # hashlib.sha256 de hash_token(), então o contador continua batendo.
    op.execute(
        "UPDATE tentativas_login "
        "SET email_hash = encode(sha256(convert_to(email, 'UTF8')), 'hex')"
    )
    op.alter_column("tentativas_login", "email_hash", nullable=False)
    op.drop_column("tentativas_login", "email")
    op.create_index(
        "ix_tentativas_login_email_hash_tentado_em",
        "tentativas_login",
        ["email_hash", "tentado_em"],
    )


def downgrade() -> None:
    op.drop_index("ix_tentativas_login_email_hash_tentado_em", table_name="tentativas_login")
    # O hash não é reversível. A tabela só guarda contador transitório de falhas,
    # então voltar significa descartar as linhas — no pior caso alguém bloqueado
    # recupera as tentativas.
    op.execute("DELETE FROM tentativas_login")
    op.add_column("tentativas_login", sa.Column("email", sa.String(255), nullable=False))
    op.drop_column("tentativas_login", "email_hash")
    op.create_index(
        "ix_tentativas_login_email_tentado_em", "tentativas_login", ["email", "tentado_em"]
    )
