"""cota da YouTube API: contagem diária por empresa e jobs que esperam a renovação

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-09

Quando a cota diária da YouTube Data API acabava, a coleta falhava e a empresa
perdia a execução (ADR-015 de docs/BANCO.md). Agora o app conta o que gasta
(`uso_cota_youtube`) e, sem cota, ADIA o job até a renovação (`jobs.disponivel_em`)
em vez de mandá-lo para a DLQ.

**RLS** ligado em `uso_cota_youtube`, sem política e sem FORCE (regra 9, ADR-010).

**Downgrade** apaga a tabela e as duas colunas; job adiado volta a poder ser
reivindicado de imediato.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uso_cota_youtube",
        sa.Column("dia", sa.Date(), nullable=False),
        sa.Column("id_empresa", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("unidades", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("dia", "id_empresa"),
    )
    op.execute('ALTER TABLE public."uso_cota_youtube" ENABLE ROW LEVEL SECURITY')

    op.add_column("jobs", sa.Column("disponivel_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("motivo_espera", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "motivo_espera")
    op.drop_column("jobs", "disponivel_em")
    op.drop_table("uso_cota_youtube")
