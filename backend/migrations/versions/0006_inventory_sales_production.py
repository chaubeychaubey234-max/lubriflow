"""Inventory subledger, sales documents and configurable manufacturing."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"


def upgrade():
    for name in ("stockpositions", "stockcounts", "reservations", "landedcosts", "salesquotes", "salesreturns", "customercredits", "boms", "productionorders"):
        table = "business_" + name
        op.create_table(table,
            sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), primary_key=True),
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(50)), sa.Column("supplier", sa.String(100)),
            sa.Column("date", sa.String(10)), sa.Column("payload", JSONB(), nullable=False))
        for field in ("status", "supplier", "date"):
            op.create_index("ix_" + table + "_" + field, table, [field])


def downgrade():
    raise RuntimeError("Restore a verified backup instead of deleting inventory and production records.")
