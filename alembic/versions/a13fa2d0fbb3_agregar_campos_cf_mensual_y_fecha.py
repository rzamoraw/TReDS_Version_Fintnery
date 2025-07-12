"""Agregar campos CF Mensual y Fecha

Revision ID: a13fa2d0fbb3
Revises: c497e6f6e2de
Create Date: 2025-07-11 15:13:32.148359

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a13fa2d0fbb3'
down_revision: Union[str, Sequence[str], None] = 'c497e6f6e2de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('financiadores', sa.Column('costo_fondos_mensual', sa.Float(), nullable=True))
    op.add_column('financiadores', sa.Column('fecha_costo_fondos', sa.Date(), nullable=True))

def downgrade():
    op.drop_column('financiadores', 'fecha_costo_fondos')
    op.drop_column('financiadores', 'costo_fondos_mensual')
    