"""docket linked journal

Revision ID: b7c8d9e0f1a2
Revises: 1005081d27c9
Create Date: 2026-11-09 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = '1005081d27c9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'petty_cash_journal_voucher',
        sa.Column('linked_journal_id', sa.Integer(),
                  sa.ForeignKey('journal_entry_master.id'), nullable=True)
    )


def downgrade():
    op.drop_column('petty_cash_journal_voucher', 'linked_journal_id')
