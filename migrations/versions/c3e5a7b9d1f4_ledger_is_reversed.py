"""accounting_ledger.is_reversed — reverse instead of delete

A posted document is undone (reback / cancel / delete-of-posted) by a
reversal posting, never by deleting ledger rows. The original posting is
flagged is_reversed=TRUE so the document may post again on re-approval:
uq_ledger_source now allows one ACTIVE (not reversed) posting per document.

Revision ID: c3e5a7b9d1f4
Revises: b2d4f6a8c0e1
Create Date: 2026-11-21 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3e5a7b9d1f4'
down_revision = 'b2d4f6a8c0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'accounting_ledger',
        sa.Column('is_reversed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # originals that already have a reversal (old cancellations, opening balances)
    op.execute("""
        UPDATE accounting_ledger o
           SET is_reversed = TRUE
         WHERE o.is_reversal = FALSE
           AND EXISTS (SELECT 1 FROM accounting_ledger r
                        WHERE r.is_reversal = TRUE AND r.reversed_posting_id = o.id)
    """)
    op.drop_index('uq_ledger_source', table_name='accounting_ledger')
    op.create_index(
        'uq_ledger_source', 'accounting_ledger', ['source_type', 'source_id'],
        unique=True,
        postgresql_where=sa.text("is_reversal = FALSE AND is_reversed = FALSE"),
    )
    op.create_index(
        'ix_ledger_reversed_posting', 'accounting_ledger', ['reversed_posting_id'],
        postgresql_where=sa.text("reversed_posting_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index('ix_ledger_reversed_posting', table_name='accounting_ledger')
    op.drop_index('uq_ledger_source', table_name='accounting_ledger')
    # NOTE: fails if a document was re-posted after a reversal (two originals).
    op.create_index(
        'uq_ledger_source', 'accounting_ledger', ['source_type', 'source_id'],
        unique=True,
        postgresql_where=sa.text("is_reversal = FALSE"),
    )
    op.drop_column('accounting_ledger', 'is_reversed')
