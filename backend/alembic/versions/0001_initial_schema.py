"""Schema inicial: 10 tabelas de domínio + jobs + jobs_dlq

Revision ID: 0001
Revises:
Create Date: 2026-09-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id_usuario", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("senha_hash", sa.String(255), nullable=False),
        sa.Column("papel", sa.String(20), nullable=False, server_default="usuario_pme"),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_usuarios_email"),
        sa.CheckConstraint("papel IN ('admin', 'usuario_pme')", name="ck_usuarios_papel"),
    )

    op.create_table(
        "modelos_analise",
        sa.Column("id_modelo", sa.Integer(), primary_key=True),
        sa.Column(
            "id_usuario",
            sa.Integer(),
            sa.ForeignKey("usuarios.id_usuario"),
            nullable=False,
        ),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("termo_pesquisa", sa.String(255), nullable=False),
        sa.Column("filtros", postgresql.JSONB(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "execucoes",
        sa.Column("id_execucao", sa.Integer(), primary_key=True),
        sa.Column(
            "id_modelo",
            sa.Integer(),
            sa.ForeignKey("modelos_analise.id_modelo"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pendente"),
        sa.Column("iniciado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("concluido_em", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pendente', 'processando', 'concluida', 'erro')",
            name="ck_execucoes_status",
        ),
    )

    op.create_table(
        "videos",
        sa.Column("id_video", sa.Integer(), primary_key=True),
        sa.Column(
            "id_execucao",
            sa.Integer(),
            sa.ForeignKey("execucoes.id_execucao", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("youtube_video_id", sa.String(32), nullable=False),
        sa.Column("titulo", sa.String(500), nullable=False),
        sa.Column("canal", sa.String(255), nullable=False),
        sa.Column("publicado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visualizacoes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("curtidas", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("youtube_video_id", name="uq_videos_youtube_video_id"),
    )

    op.create_table(
        "comentarios",
        sa.Column("id_comentario", sa.Integer(), primary_key=True),
        sa.Column(
            "id_video",
            sa.Integer(),
            sa.ForeignKey("videos.id_video", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("youtube_comment_id", sa.String(64), nullable=False),
        sa.Column("autor_hash", sa.String(64), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("publicado_em", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("youtube_comment_id", name="uq_comentarios_youtube_comment_id"),
    )

    op.create_table(
        "versoes_modelo",
        sa.Column("id_versao", sa.Integer(), primary_key=True),
        sa.Column("nome_modelo", sa.String(255), nullable=False),
        sa.Column("versao", sa.String(50), nullable=False),
        sa.Column("metricas_avaliacao", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ativo"),
        sa.CheckConstraint("status IN ('ativo', 'arquivado')", name="ck_versoes_modelo_status"),
    )

    op.create_table(
        "analises_sentimento",
        sa.Column("id_analise", sa.Integer(), primary_key=True),
        sa.Column(
            "id_comentario",
            sa.Integer(),
            sa.ForeignKey("comentarios.id_comentario", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "id_versao_modelo",
            sa.Integer(),
            sa.ForeignKey("versoes_modelo.id_versao"),
            nullable=False,
        ),
        sa.Column("sentimento", sa.String(20), nullable=False),
        sa.Column("tema", sa.String(255), nullable=True),
        sa.Column("justificativa", sa.Text(), nullable=True),
        sa.Column("processado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("id_comentario", name="uq_analises_sentimento_id_comentario"),
        sa.CheckConstraint(
            "sentimento IN ('positivo', 'negativo', 'neutro')",
            name="ck_analises_sentimento_sentimento",
        ),
    )

    op.create_table(
        "exemplos_treinamento",
        sa.Column("id_exemplo", sa.Integer(), primary_key=True),
        sa.Column(
            "id_comentario",
            sa.Integer(),
            sa.ForeignKey("comentarios.id_comentario", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("rotulo_fraco", sa.String(20), nullable=True),
        sa.Column("rotulo_humano", sa.String(20), nullable=True),
        sa.Column("split", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "split IN ('treino', 'validacao', 'teste')", name="ck_exemplos_treinamento_split"
        ),
    )

    op.create_table(
        "temas",
        sa.Column("id_tema", sa.Integer(), primary_key=True),
        sa.Column(
            "id_execucao",
            sa.Integer(),
            sa.ForeignKey("execucoes.id_execucao"),
            nullable=False,
        ),
        sa.Column("rotulo_tema", sa.String(255), nullable=False),
        sa.Column("palavras_chave", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "comentario_tema",
        sa.Column(
            "id_comentario",
            sa.Integer(),
            sa.ForeignKey("comentarios.id_comentario", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "id_tema",
            sa.Integer(),
            sa.ForeignKey("temas.id_tema", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("peso", sa.Float(), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id_job", sa.Integer(), primary_key=True),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column(
            "id_execucao",
            sa.Integer(),
            sa.ForeignKey("execucoes.id_execucao"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pendente"),
        sa.Column("tentativas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("tipo IN ('coleta', 'inferencia', 'topicos')", name="ck_jobs_tipo"),
        sa.CheckConstraint(
            "status IN ('pendente', 'processando', 'concluida', 'erro')", name="ck_jobs_status"
        ),
    )

    op.create_table(
        "jobs_dlq",
        sa.Column("id_job", sa.Integer(), primary_key=True),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column(
            "id_execucao",
            sa.Integer(),
            sa.ForeignKey("execucoes.id_execucao"),
            nullable=False,
        ),
        sa.Column("erro", sa.Text(), nullable=False),
        sa.Column("falhou_em", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("tipo IN ('coleta', 'inferencia', 'topicos')", name="ck_jobs_dlq_tipo"),
    )


def downgrade() -> None:
    op.drop_table("jobs_dlq")
    op.drop_table("jobs")
    op.drop_table("comentario_tema")
    op.drop_table("temas")
    op.drop_table("exemplos_treinamento")
    op.drop_table("analises_sentimento")
    op.drop_table("versoes_modelo")
    op.drop_table("comentarios")
    op.drop_table("videos")
    op.drop_table("execucoes")
    op.drop_table("modelos_analise")
    op.drop_table("usuarios")
