"""jobs ganha reivindicado_em, para o reaper achar job preso

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-25

Se o worker morre no meio de um job (queda do processo, deploy, OOM), o job fica
em 'processando' para sempre: o SELECT da fila so busca 'pendente', entao nenhum
outro worker o reivindica, e a execucao trava sem resultado e sem erro.

Esta coluna e o que permite distinguir "esta rodando" de "foi abandonado": ela
marca QUANDO o job foi reivindicado, e o reaper devolve a fila o que passou do
tempo limite (app/workers/fila.devolver_presos).

Nula nas linhas existentes de proposito -- nao da para inventar a hora em que um
job antigo foi reivindicado. O reaper trata nulo caindo em `criado_em`, que e
sempre anterior e portanto seguro: no pior caso devolve a fila um job velho que
ja estava perdido de qualquer jeito.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("reivindicado_em", sa.DateTime(timezone=True), nullable=True),
    )
    # O reaper varre por (status, reivindicado_em). Sem indice seria varredura
    # da tabela inteira a cada minuto -- barato hoje, caro quando a fila crescer.
    op.create_index(
        "ix_jobs_status_reivindicado_em", "jobs", ["status", "reivindicado_em"]
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_status_reivindicado_em", table_name="jobs")
    op.drop_column("jobs", "reivindicado_em")
