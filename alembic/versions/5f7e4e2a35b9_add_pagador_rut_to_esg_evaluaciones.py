"""add pagador_rut to esg_evaluaciones

Revision ID: 5f7e4e2a35b9
Revises: cfa082af7250
Create Date: 2025-08-20 15:30:04.373022

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5f7e4e2a35b9'
down_revision = 'cfa082af7250'
branch_labels = None
depends_on = None



def upgrade():
    op.add_column('esg_evaluaciones', sa.Column('pagador_rut', sa.String(length=20), nullable=True))
    # si existía proveedor_rut y quieres traspasar:
    op.execute("UPDATE esg_evaluaciones SET pagador_rut = proveedor_rut WHERE pagador_rut IS NULL")
    op.create_index('ix_esg_evaluaciones_pagador_rut', 'esg_evaluaciones', ['pagador_rut'], unique=False)
    # si luego quieres volverla NOT NULL, en SQLite es complejo; puedes dejarla nullable=True o recrear tabla.


def downgrade():
    op.drop_index('ix_esg_evaluaciones_pagador_rut', table_name='esg_evaluaciones')
    op.drop_column('esg_evaluaciones', 'pagador_rut')