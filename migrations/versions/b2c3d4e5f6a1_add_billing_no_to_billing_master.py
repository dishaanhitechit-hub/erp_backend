"""add billing_no column to billing_master

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-10-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # billing_no was renamed to erp_no by the previous migration.
    # Add billing_no back as a separate nullable column for manual user entry.
    op.add_column('billing_master', sa.Column('billing_no', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('billing_master', 'billing_no')
