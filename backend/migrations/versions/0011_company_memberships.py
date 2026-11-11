"""Explicit per-company staff memberships; additive foundation."""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'


def upgrade():
    op.create_table('company_memberships',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), primary_key=True),
        sa.Column('role', sa.String(30), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False))


def downgrade():
    raise RuntimeError('Use a verified backup; do not discard company access records.')
