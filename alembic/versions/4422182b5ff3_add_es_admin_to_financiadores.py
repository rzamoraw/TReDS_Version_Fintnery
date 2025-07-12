"""add es_admin to financiadores

Revision ID: 4422182b5ff3
Revises: a13fa2d0fbb3
Create Date: 2025-07-11 17:51:35.118020

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4422182b5ff3'
down_revision: Union[str, Sequence[str], None] = 'a13fa2d0fbb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financiadores",
        sa.Column("es_admin", sa.Boolean(), nullable=True, server_default=sa.text("0"))
    )

def downgrade() -> None:
    op.drop_column("financiadores", "es_admin")
    