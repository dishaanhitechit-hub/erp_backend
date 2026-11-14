"""runtime_store: short-lived values shared by all workers (OTP, reset tokens,
rate limits, scheduler leases). Additive only — no existing table changes.

Revision ID: a7c3e1d2b9f0
Revises: f45c5f3b734a
Create Date: 2026-11-14 14:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c3e1d2b9f0'
down_revision = 'f45c5f3b734a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'runtime_store',
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    op.create_index('ix_runtime_store_expires_at', 'runtime_store', ['expires_at'], unique=False)


def downgrade():
    op.drop_index('ix_runtime_store_expires_at', table_name='runtime_store')
    op.drop_table('runtime_store')
