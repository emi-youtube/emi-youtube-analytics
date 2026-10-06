"""aceites_termos: registro do aceite dos Termos de Uso e da Politica de Privacidade

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-06

Uma linha por (usuario, versao aceita). Tabela de INFRAESTRUTURA, nao de dominio:
existe para cumprir a LGPD (prova do aceite), nao representa conceito do negocio --
documentada na Secao 4.3.2 e no ADR-012 de docs/BANCO.md, fora do DER.

**Sem backfill.** Quem ja tem conta nao aceitou a versao 1.0: o aceite tem de ser um
ato da pessoa, nao da migracao. Essas contas aparecem com `termos_pendentes` em
`GET /auth/eu` e aceitam no proximo acesso.

**RLS** ligado, sem politica e sem FORCE (regra 9 do CLAUDE.md, ADR-010).

**Downgrade** apaga a tabela e, com ela, o registro dos aceites ja feitos.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aceites_termos",
        sa.Column("id_aceite", sa.Integer(), primary_key=True),
        sa.Column(
            "id_usuario",
            sa.Integer(),
            sa.ForeignKey("usuarios.id_usuario", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("versao_termos", sa.String(20), nullable=False),
        sa.Column(
            "aceito_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Um aceite por versao: e o que torna `POST /conta/aceitar-termos` idempotente
        # mesmo com dois cliques simultaneos. Tambem serve de indice por `id_usuario`
        # (coluna da esquerda), que e a unica busca feita na tabela.
        sa.UniqueConstraint("id_usuario", "versao_termos", name="uq_aceites_termos_usuario_versao"),
    )
    op.execute('ALTER TABLE public."aceites_termos" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("aceites_termos")
