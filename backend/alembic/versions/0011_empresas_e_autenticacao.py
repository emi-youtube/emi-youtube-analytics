"""empresas (isolamento multiusuario), convites, redefinicao de senha e rotacao de refresh

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06

O isolamento deixa de ser por USUARIO e passa a ser por EMPRESA (ADR-011 em
docs/BANCO.md): varias pessoas da mesma empresa veem os mesmos modelos, execucoes e
resultados. `modelos_analise.id_usuario` continua, agora como AUTOR; a posse e
`modelos_analise.id_empresa`.

**Backfill na mesma migracao.** Cada usuario existente ganha uma empresa propria
(nome = parte local do e-mail), vira 'dono' dela, e os modelos dele passam a ser
dessa empresa. Ninguem passa a ver nada que nao via antes: a empresa de cada um tem
exatamente um membro. As colunas nascem NULAS, sao preenchidas e so entao viram NOT
NULL -- e o unico jeito de acrescentar coluna obrigatoria a uma tabela com linhas.

**RLS** ligado nas tres tabelas novas, sem politica e sem FORCE (regra 9 do
CLAUDE.md, ADR-010).

**Downgrade** remove tudo o que o upgrade criou. Perde-se o que so existe no modelo
novo: quem entrou por convite continua com a conta, mas deixa de ver os modelos
criados pelos colegas (volta o isolamento por usuario).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELAS_NOVAS = ("empresas", "convites", "tokens_redefinicao_senha")


def upgrade() -> None:
    op.create_table(
        "empresas",
        sa.Column("id_empresa", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Temporaria: liga cada empresa do backfill ao usuario que a originou.
        sa.Column("_id_usuario_origem", sa.Integer(), nullable=True),
    )

    # --- usuarios: empresa e papel dentro dela ---
    op.add_column("usuarios", sa.Column("id_empresa", sa.Integer(), nullable=True))
    op.add_column("usuarios", sa.Column("papel_empresa", sa.String(10), nullable=True))

    # Uma empresa por usuario existente. `criada_em` herda o cadastro do usuario, para
    # o historico nao dizer que a empresa nasceu no dia da migracao.
    op.execute(
        """
        INSERT INTO empresas (nome, criada_em, _id_usuario_origem)
        SELECT left(split_part(email, '@', 1), 120), criado_em, id_usuario
        FROM usuarios
        ORDER BY id_usuario
        """
    )
    op.execute(
        """
        UPDATE usuarios u
        SET id_empresa = e.id_empresa, papel_empresa = 'dono'
        FROM empresas e
        WHERE e._id_usuario_origem = u.id_usuario
        """
    )
    op.drop_column("empresas", "_id_usuario_origem")

    op.alter_column("usuarios", "id_empresa", nullable=False)
    op.alter_column("usuarios", "papel_empresa", nullable=False)
    op.create_foreign_key(
        "fk_usuarios_id_empresa", "usuarios", "empresas", ["id_empresa"], ["id_empresa"]
    )
    op.create_check_constraint(
        "ck_usuarios_papel_empresa", "usuarios", "papel_empresa IN ('dono', 'membro')"
    )
    op.create_index("ix_usuarios_id_empresa", "usuarios", ["id_empresa"])

    # --- modelos_analise: a posse passa a ser da empresa do autor ---
    op.add_column("modelos_analise", sa.Column("id_empresa", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE modelos_analise m
        SET id_empresa = u.id_empresa
        FROM usuarios u
        WHERE u.id_usuario = m.id_usuario
        """
    )
    op.alter_column("modelos_analise", "id_empresa", nullable=False)
    op.create_foreign_key(
        "fk_modelos_analise_id_empresa",
        "modelos_analise",
        "empresas",
        ["id_empresa"],
        ["id_empresa"],
    )
    op.create_index("ix_modelos_analise_id_empresa", "modelos_analise", ["id_empresa"])

    # --- convites ---
    op.create_table(
        "convites",
        sa.Column("id_convite", sa.Integer(), primary_key=True),
        sa.Column(
            "id_empresa",
            sa.Integer(),
            sa.ForeignKey("empresas.id_empresa", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("papel_empresa", sa.String(10), nullable=False),
        sa.Column(
            "criado_por",
            sa.Integer(),
            sa.ForeignKey("usuarios.id_usuario", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("token_hash", name="uq_convites_token_hash"),
        sa.CheckConstraint("papel_empresa IN ('dono', 'membro')", name="ck_convites_papel_empresa"),
    )
    op.create_index("ix_convites_id_empresa", "convites", ["id_empresa"])

    # --- tokens_redefinicao_senha ---
    op.create_table(
        "tokens_redefinicao_senha",
        sa.Column("id_token", sa.Integer(), primary_key=True),
        sa.Column(
            "id_usuario",
            sa.Integer(),
            sa.ForeignKey("usuarios.id_usuario", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("token_hash", name="uq_tokens_redefinicao_senha_token_hash"),
    )
    op.create_index(
        "ix_tokens_redefinicao_senha_id_usuario", "tokens_redefinicao_senha", ["id_usuario"]
    )

    # --- tokens_atualizacao: rotacao com deteccao de reuso ---
    # Coluna nula, sem default: o codigo antigo, que nao a conhece, continua inserindo.
    op.add_column(
        "tokens_atualizacao",
        sa.Column("substituido_em", sa.DateTime(timezone=True), nullable=True),
    )
    # Revogar "todos os tokens do usuario" (reuso, troca de senha) filtra por ele.
    op.create_index("ix_tokens_atualizacao_id_usuario", "tokens_atualizacao", ["id_usuario"])

    for tabela in TABELAS_NOVAS:
        op.execute(f'ALTER TABLE public."{tabela}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index("ix_tokens_atualizacao_id_usuario", table_name="tokens_atualizacao")
    op.drop_column("tokens_atualizacao", "substituido_em")

    op.drop_index("ix_tokens_redefinicao_senha_id_usuario", table_name="tokens_redefinicao_senha")
    op.drop_table("tokens_redefinicao_senha")

    op.drop_index("ix_convites_id_empresa", table_name="convites")
    op.drop_table("convites")

    op.drop_index("ix_modelos_analise_id_empresa", table_name="modelos_analise")
    op.drop_constraint("fk_modelos_analise_id_empresa", "modelos_analise", type_="foreignkey")
    op.drop_column("modelos_analise", "id_empresa")

    op.drop_index("ix_usuarios_id_empresa", table_name="usuarios")
    op.drop_constraint("ck_usuarios_papel_empresa", "usuarios", type_="check")
    op.drop_constraint("fk_usuarios_id_empresa", "usuarios", type_="foreignkey")
    op.drop_column("usuarios", "papel_empresa")
    op.drop_column("usuarios", "id_empresa")

    op.drop_table("empresas")
