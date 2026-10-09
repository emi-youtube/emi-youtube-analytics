"""guarda dos dados do YouTube: texto apagado em 30 dias, título atualizado

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-09

As políticas dos YouTube API Services (III.E.4.d) limitam a 30 dias a guarda do que
vem da API sem login do autor: depois disso, apagar ou atualizar. O expurgo
(`app/workers/expurgo.py`) apaga o texto dos comentários e mantém o resultado, e
atualiza o título e o canal dos vídeos antes de vencerem (ADR-015, docs/BANCO.md).

- `comentarios.texto`, `autor_hash` e `youtube_comment_id` passam a aceitar nulo:
  nulo é "apagado pelo expurgo". A linha fica, porque a análise de sentimento e o
  tema do comentário penduram nela.
- `execucoes.comentarios_apagados_em`: quando o expurgo apagou os textos daquela
  execução. Nulo enquanto ainda estão disponíveis.
- `videos.metadados_em`: quando o título, o canal e a data do vídeo vieram da API.
  As linhas existentes herdam o início da execução, que é quando foram coletadas.
  Nulo = apagados (vídeo fora do ar ou atualização impossível a tempo).

Nenhuma tabela nova, então nada de RLS aqui (regra 9).

**Downgrade** só volta o NOT NULL se não houver linha apagada; com expurgo já feito,
o texto não volta, e o downgrade recusa em vez de inventar um texto vazio.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("comentarios", "texto", existing_type=sa.Text(), nullable=True)
    op.alter_column("comentarios", "autor_hash", existing_type=sa.String(64), nullable=True)
    op.alter_column("comentarios", "youtube_comment_id", existing_type=sa.String(64), nullable=True)

    op.add_column(
        "execucoes",
        sa.Column("comentarios_apagados_em", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "videos",
        sa.Column(
            "metadados_em",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    # Os vídeos que já existem foram coletados no início da execução, não agora.
    op.execute(
        """
        UPDATE videos AS v
           SET metadados_em = COALESCE(e.iniciado_em, e.concluido_em, v.metadados_em)
          FROM execucoes AS e
         WHERE e.id_execucao = v.id_execucao
        """
    )


def downgrade() -> None:
    apagados = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM comentarios WHERE texto IS NULL"))
        .scalar()
    )
    if apagados:
        raise RuntimeError(
            f"{apagados} comentario(s) ja tiveram o texto apagado pelo expurgo; "
            "o downgrade nao tem como devolver o NOT NULL sem inventar texto."
        )

    op.drop_column("videos", "metadados_em")
    op.drop_column("execucoes", "comentarios_apagados_em")
    op.alter_column(
        "comentarios", "youtube_comment_id", existing_type=sa.String(64), nullable=False
    )
    op.alter_column("comentarios", "autor_hash", existing_type=sa.String(64), nullable=False)
    op.alter_column("comentarios", "texto", existing_type=sa.Text(), nullable=False)
