"""➕ Agrega columna nombre_financiador en condiciones_por_pagador

Revision ID: d869cd281c27
Revises: 797289c16180
Create Date: 2025-07-10 12:05:46.845354
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# --- Identificadores de Alembic ---
revision: str = "d869cd281c27"
down_revision: Union[str, Sequence[str], None] = "797289c16180"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
# -----------------------------------

def upgrade() -> None:
    """Añade la columna nombre_financiador."""
    op.add_column(
        "condiciones_por_pagador",
        sa.Column("nombre_financiador", sa.String(), nullable=True)
    )

def downgrade() -> None:
    """Revierte el cambio."""
    op.drop_column("condiciones_por_pagador", "nombre_financiador")