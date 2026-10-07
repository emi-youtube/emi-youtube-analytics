"""cadastros_pendentes: cadastro de empresa nova so vale depois de confirmar o e-mail

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-07

O cadastro respondia 409 quando o e-mail ja tinha conta, o que permitia descobrir
quem esta cadastrado. Agora quem cria empresa nova recebe um link por e-mail, e a
conta so nasce quando a pessoa o abre (ADR-014 de docs/BANCO.md). Ate la, os dados
ficam nesta tabela de INFRAESTRUTURA, fora do DER.

Um pedido por e-mail (UNIQUE em `email`); o token fica so como SHA-256. As linhas
vencidas saem na propria escrita (regra 7 do CLAUDE.md).

**RLS** ligado, sem politica e sem FORCE (regra 9 do CLAUDE.md, ADR-010).

**Downgrade** apaga a tabela e, com ela, os cadastros ainda nao confirmados.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cadastros_pendentes",
        sa.Column("id_cadastro", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("nome_empresa", sa.String(120), nullable=False),
        sa.Column("senha_hash", sa.String(255), nullable=False),
        sa.Column("versao_termos", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("email", name="uq_cadastros_pendentes_email"),
        sa.UniqueConstraint("token_hash", name="uq_cadastros_pendentes_token_hash"),
    )
    op.execute('ALTER TABLE public."cadastros_pendentes" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("cadastros_pendentes")
