"""Encrypted authenticator enrollment and replay protection."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"


def upgrade():
    op.add_column("users", sa.Column("mfa_secret", sa.String(500)))
    op.add_column("users", sa.Column("mfa_pending", sa.String(500)))
    op.add_column("users", sa.Column("mfa_pending_expires", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("mfa_last_step", sa.Integer()))
    op.add_column("users", sa.Column("mfa_recovery", JSONB(), nullable=False, server_default="[]"))


def downgrade():
    raise RuntimeError("Restore a verified backup instead of removing account security data.")
