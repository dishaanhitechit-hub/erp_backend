"""bank statement import: batches, transactions, link log + bank_statement page

Adds the Bank Statement Import module (Finance > Account > Bank Statements) and
the link between imported bank transactions and petty cash expense dockets.

  * bank_statement_batch   — one uploaded statement file (import history)
  * bank_transaction       — one statement line; linked_docket_id UNIQUE so a
                             transaction can belong to only one docket
  * bank_transaction_log   — audit trail (LINK / UNLINK / RECONCILE / ...)
  * feature_pages          — 'bank_statement' permission page (idempotent),
                             placed in the same sub-module as 'petty_cash'

Revision ID: b5a7c1d9e3f2
Revises: c8251e9264fe
Create Date: 2026-11-18 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b5a7c1d9e3f2'
down_revision = 'c8251e9264fe'
branch_labels = None
depends_on = None

_PAGE = ("bank_statement", "Bank Statements", "/finance-management/account/bank-statement")


def upgrade():
    op.create_table(
        'bank_statement_batch',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bank_account_id', sa.Integer(), sa.ForeignKey('bank_cash.id'), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=True),
        sa.Column('total_rows', sa.Integer(), server_default='0'),
        sa.Column('imported_count', sa.Integer(), server_default='0'),
        sa.Column('skipped_count', sa.Integer(), server_default='0'),
        sa.Column('failed_count', sa.Integer(), server_default='0'),
        sa.Column('from_date', sa.Date(), nullable=True),
        sa.Column('to_date', sa.Date(), nullable=True),
        sa.Column('total_debit', sa.Numeric(15, 2), server_default='0'),
        sa.Column('total_credit', sa.Numeric(15, 2), server_default='0'),
        sa.Column('status', sa.String(20), server_default='Active'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('reverted_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reverted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_bank_statement_batch_bank_account_id', 'bank_statement_batch', ['bank_account_id'])

    op.create_table(
        'bank_transaction',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bank_account_id', sa.Integer(), sa.ForeignKey('bank_cash.id'), nullable=False),
        sa.Column('import_batch_id', sa.Integer(),
                  sa.ForeignKey('bank_statement_batch.id', ondelete='CASCADE'), nullable=False),
        sa.Column('row_no', sa.Integer(), nullable=True),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('by_dr', sa.String(200), nullable=True),
        sa.Column('to_cr', sa.String(200), nullable=True),
        sa.Column('debit_amount', sa.Numeric(15, 2), server_default='0'),
        sa.Column('credit_amount', sa.Numeric(15, 2), server_default='0'),
        sa.Column('balance', sa.Numeric(15, 2), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('transaction_type', sa.String(2), nullable=False),
        sa.Column('site_code', sa.String(50), sa.ForeignKey('projects.project_code'), nullable=True),
        sa.Column('reference_number', sa.String(100), nullable=True),
        sa.Column('is_upi', sa.Boolean(), server_default=sa.false()),
        sa.Column('dedupe_key', sa.String(64), nullable=False),
        sa.Column('reconciliation_status', sa.String(20), nullable=False, server_default='Unreconciled'),
        sa.Column('linked_docket_id', sa.Integer(),
                  sa.ForeignKey('petty_cash_docket_voucher.id', ondelete='SET NULL'), nullable=True),
        sa.Column('linked_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('linked_at', sa.DateTime(), nullable=True),
        sa.Column('reconciled_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reconciled_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('bank_account_id', 'dedupe_key', name='uq_bank_txn_account_dedupe'),
        sa.UniqueConstraint('linked_docket_id', name='uq_bank_transaction_linked_docket_id'),
        sa.CheckConstraint("transaction_type IN ('DR', 'CR')", name='ck_bank_txn_type'),
    )
    op.create_index('ix_bank_transaction_bank_account_id', 'bank_transaction', ['bank_account_id'])
    op.create_index('ix_bank_transaction_import_batch_id', 'bank_transaction', ['import_batch_id'])
    op.create_index('ix_bank_transaction_transaction_date', 'bank_transaction', ['transaction_date'])
    op.create_index('ix_bank_transaction_site_code', 'bank_transaction', ['site_code'])
    op.create_index('ix_bank_transaction_is_upi', 'bank_transaction', ['is_upi'])
    op.create_index('ix_bank_transaction_reconciliation_status', 'bank_transaction', ['reconciliation_status'])
    op.create_index('ix_bank_txn_account_site_status', 'bank_transaction',
                    ['bank_account_id', 'site_code', 'reconciliation_status'])

    op.create_table(
        'bank_transaction_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('transaction_id', sa.Integer(),
                  sa.ForeignKey('bank_transaction.id', ondelete='CASCADE'), nullable=False),
        sa.Column('docket_id', sa.Integer(), nullable=True),
        sa.Column('docket_no', sa.String(30), nullable=True),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('note', sa.String(255), nullable=True),
        sa.Column('action_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('action_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_bank_transaction_log_transaction_id', 'bank_transaction_log', ['transaction_id'])

    # ── permission page (same sub-module as petty_cash; idempotent) ──
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT submodule_id FROM feature_pages WHERE page_code = 'petty_cash' LIMIT 1")).fetchone()
    if row:
        sub_id = row[0]
    else:
        main = conn.execute(sa.text("SELECT id FROM main_modules WHERE module_name = 'Finance Management' LIMIT 1")).fetchone()
        main_id = main[0] if main else conn.execute(sa.text(
            "INSERT INTO main_modules (module_name, icon) VALUES ('Finance Management', 'Wallet') RETURNING id")).fetchone()[0]
        sub = conn.execute(sa.text(
            "SELECT id FROM sub_modules WHERE main_module_id = :mid AND submodule_name = 'Account' LIMIT 1"),
            {"mid": main_id}).fetchone()
        sub_id = sub[0] if sub else conn.execute(sa.text(
            "INSERT INTO sub_modules (main_module_id, submodule_name) VALUES (:mid, 'Account') RETURNING id"),
            {"mid": main_id}).fetchone()[0]
    code, name, route = _PAGE
    conn.execute(sa.text(
        """INSERT INTO feature_pages (submodule_id, page_name, page_code, route_path, is_menu_visible, sort_order)
        SELECT :sid, :name, :code, :route, TRUE, 99
        WHERE NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = :code)"""),
        {"sid": sub_id, "name": name, "code": code, "route": route})


def downgrade():
    op.drop_index('ix_bank_transaction_log_transaction_id', table_name='bank_transaction_log')
    op.drop_table('bank_transaction_log')
    for ix in ('ix_bank_txn_account_site_status', 'ix_bank_transaction_reconciliation_status',
               'ix_bank_transaction_is_upi', 'ix_bank_transaction_site_code',
               'ix_bank_transaction_transaction_date', 'ix_bank_transaction_import_batch_id',
               'ix_bank_transaction_bank_account_id'):
        op.drop_index(ix, table_name='bank_transaction')
    op.drop_table('bank_transaction')
    op.drop_index('ix_bank_statement_batch_bank_account_id', table_name='bank_statement_batch')
    op.drop_table('bank_statement_batch')
    # feature_pages row is left in place on purpose: permissions may already reference it.
