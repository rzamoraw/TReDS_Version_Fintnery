from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import DateTime, Date

# revision identifiers, used by Alembic.
revision = "1e4afb1c9b0a"
down_revision = "760ad6898391"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # ─────────────────── columnas en facturas ───────────────────
    cols = {c["name"]: c for c in insp.get_columns("facturas")}

    # estado_confirmacion
    if "estado_confirmacion" not in cols:
        op.add_column("facturas", sa.Column("estado_confirmacion", sa.String(), nullable=True))

    # fecha_pago_real
    if "fecha_pago_real" not in cols:
        op.add_column("facturas", sa.Column("fecha_pago_real", sa.Date(), nullable=True))

    # fecha_confirmacion -> aseguramos DateTime
    fc = cols.get("fecha_confirmacion")
    if fc is None:
        # no existe: crear directamente como DateTime
        with op.batch_alter_table("facturas") as batch_op:
            batch_op.add_column(sa.Column("fecha_confirmacion", DateTime(), nullable=True))
    else:
        # existe: si es Date, migrar a DateTime con add/copy/drop/rename (compatible SQLite)
        if isinstance(fc["type"], DateTime):
            pass
        else:
            with op.batch_alter_table("facturas") as batch_op:
                batch_op.add_column(sa.Column("fecha_confirmacion_tmp", DateTime(), nullable=True))
            op.execute("""
                UPDATE facturas
                SET fecha_confirmacion_tmp = fecha_confirmacion
            """)
            with op.batch_alter_table("facturas") as batch_op:
                batch_op.drop_column("fecha_confirmacion")
                batch_op.alter_column("fecha_confirmacion_tmp", new_column_name="fecha_confirmacion")

    # ─────────────────── tablas nuevas ───────────────────
    existing_tables = set(insp.get_table_names())

    if "pagador_profiles" not in existing_tables:
        op.create_table(
            "pagador_profiles",
            sa.Column("rut", sa.String(), primary_key=True),
            sa.Column("razon_social", sa.String()),
            sa.Column("nombre_fantasia", sa.String(), nullable=True),
            sa.Column("sector_ciiu", sa.String(), nullable=True),
            sa.Column("email_tesoreria", sa.String(), nullable=True),
            sa.Column("telefono", sa.String(), nullable=True),
            sa.Column("sitio_web", sa.String(), nullable=True),
            sa.Column("esg_json", sa.JSON(), nullable=True),
        )

    if "esg_certificaciones" not in existing_tables:
        op.create_table(
            "esg_certificaciones",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("rut", sa.String(), nullable=False),
            sa.Column("tipo", sa.String(), nullable=False),
            sa.Column("emisor", sa.String(), nullable=True),
            sa.Column("valido_hasta", sa.Date(), nullable=True),
            sa.Column("enlace", sa.String(), nullable=True),
        )
        # índice para búsquedas por RUT
        op.create_index(
            "ix_esg_certificaciones_rut",
            "esg_certificaciones",
            ["rut"],
            unique=False
        )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # Tablas
    if "esg_certificaciones" in insp.get_table_names():
        # borrar índice si existe (no falla si no está)
        try:
            op.drop_index("ix_esg_certificaciones_rut", table_name="esg_certificaciones")
        except Exception:
            pass
        op.drop_table("esg_certificaciones")

    if "pagador_profiles" in insp.get_table_names():
        op.drop_table("pagador_profiles")

    # Columnas en facturas (drop si existen)
    cols = {c["name"] for c in insp.get_columns("facturas")}
    with op.batch_alter_table("facturas") as batch_op:
        if "fecha_confirmacion" in cols:
            batch_op.drop_column("fecha_confirmacion")
    with op.batch_alter_table("facturas") as batch_op:
        if "fecha_pago_real" in cols:
            batch_op.drop_column("fecha_pago_real")
        if "estado_confirmacion" in cols:
            batch_op.drop_column("estado_confirmacion")