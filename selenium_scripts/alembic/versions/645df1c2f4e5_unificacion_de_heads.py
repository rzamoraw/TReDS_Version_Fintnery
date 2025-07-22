"""unificacion de heads

Revision ID: 645df1c2f4e5
Revises: 040f433ea7a0, bfcd54a3a1aa
Create Date: 2025-07-21 09:48:56.539637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '645df1c2f4e5'
down_revision: Union[str, Sequence[str], None] = ('040f433ea7a0', 'bfcd54a3a1aa')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
