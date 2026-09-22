"""exemplos_treinamento.split passa a aceitar NULL (particao ainda nao atribuida)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-22

O split era NOT NULL, entao a exportacao do corpus precisava inventar uma
particao no momento em que o exemplo nascia -- antes de existir qualquer rotulo.
Isso recria a circularidade da Secao 4.1.2: o conjunto de teste acabava sorteado
junto do corpus de rotulo fraco, e avaliar o modelo contra ele deixaria de medir
generalizacao (CLAUDE.md regra 6, "conjunto de teste e so humano").

Agora NULL significa "particao ainda nao atribuida". A atribuicao acontece DEPOIS
da rotulagem fraca e da validacao humana, quando da para estratificar por rotulo e
reservar para teste so o que tem rotulo humano.

O CHECK continua valendo para os valores nao nulos e nao precisa ser recriado:
em SQL, `NULL IN ('treino','validacao','teste')` avalia para NULL, e um CHECK so
reprova quando o resultado e FALSE. NULL passa, os valores invalidos continuam
barrados.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "exemplos_treinamento",
        "split",
        existing_type=sa.String(20),
        nullable=True,
    )


def downgrade() -> None:
    # Voltar para NOT NULL exige decidir a particao das linhas que estao com NULL.
    # Atribuir 'treino' em massa aqui seria a decisao errada em silencio: exemplo
    # de teste viraria exemplo de treino e contaminaria a avaliacao. Entao o
    # downgrade falha de proposito enquanto houver NULL, e quem reverte escolhe.
    conexao = op.get_bind()
    pendentes = conexao.scalar(
        sa.text("SELECT count(*) FROM exemplos_treinamento WHERE split IS NULL")
    )
    if pendentes:
        raise RuntimeError(
            f"{pendentes} exemplo(s) com split NULL. Atribua as particoes antes de "
            "reverter esta migration -- preencher automaticamente contaminaria a avaliacao."
        )

    op.alter_column(
        "exemplos_treinamento",
        "split",
        existing_type=sa.String(20),
        nullable=False,
    )
