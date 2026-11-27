"""add pl_section to group_master

Revision ID: a1b2c3d4e5f6
Revises: ff0205dd9c6f
Create Date: 2026-11-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'ff0205dd9c6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'group_master',
        sa.Column('pl_section', sa.String(length=20), nullable=True)
    )


def downgrade():
    op.drop_column('group_master', 'pl_section')
