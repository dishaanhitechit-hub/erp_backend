"""add indexes on accounting_ledger_lines for report query performance

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5b7d9f2
Create Date: 2026-11-20 22:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2d4f6a8c0e1'
down_revision = 'a1c3e5b7d9f2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_ledger_lines_cc',
        'accounting_ledger_lines',
        ['account_type', 'cc_id'],
        postgresql_where=sa.text("account_type = 'CC'"),
    )
    op.create_index(
        'ix_ledger_lines_vendor',
        'accounting_ledger_lines',
        ['account_type', 'vendor_id'],
        postgresql_where=sa.text("account_type = 'Vendor'"),
    )
    op.create_index(
        'ix_ledger_lines_bank',
        'accounting_ledger_lines',
        ['account_type', 'bank_cash_id'],
        postgresql_where=sa.text("account_type = 'BankCash'"),
    )
    op.create_index(
        'ix_ledger_lines_posting',
        'accounting_ledger_lines',
        ['posting_id', 'account_type'],
    )


def downgrade():
    op.drop_index('ix_ledger_lines_posting', table_name='accounting_ledger_lines')
    op.drop_index('ix_ledger_lines_bank', table_name='accounting_ledger_lines')
    op.drop_index('ix_ledger_lines_vendor', table_name='accounting_ledger_lines')
    op.drop_index('ix_ledger_lines_cc', table_name='accounting_ledger_lines')
