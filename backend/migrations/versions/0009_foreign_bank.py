"""Foreign bank currency-unit audit movements."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision="0009"
down_revision="0008"
def upgrade():
    table="business_bankfxmovements"
    op.create_table(table,sa.Column("tenant_id",sa.String(36),sa.ForeignKey("tenants.id"),primary_key=True),sa.Column("id",sa.String(100),primary_key=True),sa.Column("position",sa.Integer(),nullable=False),sa.Column("status",sa.String(50)),sa.Column("supplier",sa.String(100)),sa.Column("date",sa.String(10)),sa.Column("payload",JSONB(),nullable=False))
    for field in ("status","supplier","date"):op.create_index("ix_"+table+"_"+field,table,[field])
def downgrade():
    raise RuntimeError("Restore a verified backup rather than dropping bank audit history.")
