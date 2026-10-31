"""swap erp_no and billing_no on billing_master

The previous migration renamed billing_no → erp_no (holding manual data).
This migration restores that column as billing_no and adds a fresh erp_no
column for the auto-generated system document number.

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
    # Step 1: rename erp_no (which holds old manual bill numbers) → billing_no
    op.alter_column('billing_master', 'erp_no',
                    new_column_name='billing_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)

    # Step 2: add fresh erp_no column for auto-generated system ERP number
    op.add_column('billing_master', sa.Column('erp_no', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('billing_master', 'erp_no')
    op.alter_column('billing_master', 'billing_no',
                    new_column_name='erp_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)
