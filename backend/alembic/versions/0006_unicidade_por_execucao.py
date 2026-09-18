"""Unicidade de video/comentario passa a ser por execucao, nao global

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18

A UK global em videos.youtube_video_id impedia coletar o mesmo video numa
segunda execucao -- inclusive de OUTRO usuario analisando o mesmo anuncio
publico, que e um cenario normal do produto. Como apagar uma EXECUCAO ja apaga
seus VIDEOS em cascata, a linha de VIDEOS e o retrato de uma coleta, e a
unicidade correta e (id_execucao, youtube_video_id). Mesmo raciocinio para
COMENTARIOS, por (id_video, youtube_comment_id).

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_videos_youtube_video_id", "videos", type_="unique")
    op.create_unique_constraint(
        "uq_videos_execucao_video", "videos", ["id_execucao", "youtube_video_id"]
    )

    op.drop_constraint("uq_comentarios_youtube_comment_id", "comentarios", type_="unique")
    op.create_unique_constraint(
        "uq_comentarios_video_comentario", "comentarios", ["id_video", "youtube_comment_id"]
    )


def downgrade() -> None:
    # Voltar para a UK global pode falhar se ja houver o mesmo video em duas
    # execucoes -- que e exatamente o caso que esta migration foi criada para
    # permitir. Nesse cenario, limpe as execucoes duplicadas antes.
    op.drop_constraint("uq_comentarios_video_comentario", "comentarios", type_="unique")
    op.create_unique_constraint(
        "uq_comentarios_youtube_comment_id", "comentarios", ["youtube_comment_id"]
    )

    op.drop_constraint("uq_videos_execucao_video", "videos", type_="unique")
    op.create_unique_constraint("uq_videos_youtube_video_id", "videos", ["youtube_video_id"])
