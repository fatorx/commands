"""infra_base — migration marcadora.

Estabelece a cabeça inicial do grafo de migrations. Sem mudanças de schema:
o domínio ainda não tem tabelas; as próximas migrations adicionam o schema
real (ex.: log de execução de comandos).

Revision ID: 0001_infra_base
Revises:
Create Date: 2026-08-18 23:33:50.043400
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_infra_base"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass