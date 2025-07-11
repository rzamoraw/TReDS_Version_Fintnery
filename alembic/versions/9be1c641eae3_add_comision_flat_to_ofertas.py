"""add comision_flat to ofertas

Revision ID: 9be1c641eae3
Revises: d869cd281c27
Create Date: 2025-07-10 15:42:04.687239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9be1c641eae3'
down_revision: Union[str, Sequence[str], None] = 'd869cd281c27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ofertas_financiamiento",
        sa.Column("comision_flat", sa.Float(), nullable=True, server_default="0")
    )
    # Si añadirás precio_cesion:
    op.add_column(
        "ofertas_financiamiento",
        sa.Column("precio_cesion", sa.Float(), nullable=True)
    )

def downgrade() -> None:
    op.drop_column("ofertas_financiamiento", "precio_cesion")
    op.drop_column("ofertas_financiamiento", "comision_flat")
