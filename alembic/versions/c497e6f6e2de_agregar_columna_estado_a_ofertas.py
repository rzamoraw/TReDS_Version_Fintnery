from alembic import op
import sqlalchemy as sa

# Identificadores propios de tu archivo generado:
revision = 'c497e6f6e2de'  # DEJA el que se haya generado automáticamente
down_revision = '6028555466fe'  # deja esta si es tu última migración válida
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('ofertas_financiamiento', sa.Column('estado', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('ofertas_financiamiento', 'estado')