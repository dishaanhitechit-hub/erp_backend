"""communication (rohan)

Revision ID: 3594a8ff06df
Revises: cec4963b1f98
Create Date: 2026-10-31 06:49:13.487450

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '3594a8ff06df'
down_revision = 'cec4963b1f98'
branch_labels = None
depends_on = None


def upgrade():
    # billing_master unique constraint intentionally skipped — duplicate billing_no values exist
    # comm_call_signals columns already correct from cec4963b1f98 migration — no changes needed
    pass


def downgrade():
    pass
