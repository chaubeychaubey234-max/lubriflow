"""Sales, treasury, asset, currency and tax record containers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"


def upgrade():
    for name in ("salesorders", "deliveries", "salesinvoices", "customerpayments", "bankstatements", "assets", "depreciationruns", "exchangerates", "taxreturns"):
        table = "business_" + name
        op.create_table(table, sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), primary_key=True), sa.Column("id", sa.String(100), primary_key=True), sa.Column("position", sa.Integer(), nullable=False), sa.Column("status", sa.String(50)), sa.Column("supplier", sa.String(100)), sa.Column("date", sa.String(10)), sa.Column("payload", JSONB(), nullable=False))
        op.create_index("ix_" + table + "_status", table, ["status"])
        op.create_index("ix_" + table + "_supplier", table, ["supplier"])
        op.create_index("ix_" + table + "_date", table, ["date"])


def downgrade():
    raise RuntimeError("Restore a verified backup instead of removing commercial records.")
