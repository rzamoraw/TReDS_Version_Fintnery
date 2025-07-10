"""add cascade to condiciones & ensure costo_fondos exists

Revision ID: 797289c16180
Revises: d0dc63c0281b
Create Date: 2025-07-10 11:02:00.510371
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "797289c16180"
down_revision: Union[str, Sequence[str], None] = "d0dc63c0281b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1) añadir columna costo_fondos si no existe ---
    with op.batch_alter_table("financiadores") as batch:
        batch.add_column(
            sa.Column("costo_fondos", sa.Float(), server_default="0", nullable=False)
        )

    # --- 2) recrear FK con ON DELETE CASCADE ---
    op.drop_constraint(
        "condiciones_por_pagador_financiador_id_fkey",
        "condiciones_por_pagador",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "condiciones_por_pagador_financiador_id_fkey",
        "condiciones_por_pagador",
        "financiadores",
        ["financiador_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # revertir FK
    op.drop_constraint(
        "condiciones_por_pagador_financiador_id_fkey",
        "condiciones_por_pagador",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "condiciones_por_pagador_financiador_id_fkey",
        "condiciones_por_pagador",
        "financiadores",
        ["financiador_id"],
        ["id"],
    )

    # quitar columna
    with op.batch_alter_table("financiadores") as batch:
        batch.drop_column("costo_fondos")