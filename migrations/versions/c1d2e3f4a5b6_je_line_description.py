"""je line description

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-11-09 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'journal_entry_lines',
        sa.Column('description', sa.String(255), nullable=True)
    )


def downgrade():
    op.drop_column('journal_entry_lines', 'description')
