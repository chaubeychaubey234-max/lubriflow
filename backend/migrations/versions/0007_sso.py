"""Explicit federated identity links and single-use login attempts."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"


def upgrade():
    op.create_table("sso_identities",
        sa.Column("issuer", sa.String(500), primary_key=True),
        sa.Column("subject", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False))
    op.create_index("ix_sso_identities_user_id", "sso_identities", ["user_id"])
    op.create_table("sso_attempts", sa.Column("state_hash", sa.String(64), primary_key=True),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    raise RuntimeError("Restore a verified backup rather than removing identity bindings.")
