"""Initial purchasing schema.

Revision ID: 0001
"""

from alembic import op
from pathlib import Path

revision = "0001"
down_revision = None


def upgrade():
    # Read a versioned schema snapshot, never current application models.
    source = Path(__file__).with_name("0001_schema.sql").read_text()
    for statement in source.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead.")
