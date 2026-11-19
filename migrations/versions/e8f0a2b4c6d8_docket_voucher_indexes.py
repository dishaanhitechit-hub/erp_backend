"""index docket voucher list lookups

The docket list filters petty_cash_docket_voucher by project_code (ordered by
id) and loads lines by petty_cash_docket_voucher_detail.voucher_id. Neither
column had an index (Postgres does not index foreign keys), so both were
full-table scans. IF NOT EXISTS keeps it safe if an index was added by hand.

Revision ID: e8f0a2b4c6d8
Revises: d7e9f1a3b5c2
Create Date: 2026-11-19 13:00:00.000000

"""
from alembic import op

revision = 'e8f0a2b4c6d8'
down_revision = 'd7e9f1a3b5c2'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE INDEX IF NOT EXISTS ix_pcdv_project_code_id "
               "ON petty_cash_docket_voucher (project_code, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_petty_cash_docket_voucher_detail_voucher_id "
               "ON petty_cash_docket_voucher_detail (voucher_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_petty_cash_docket_voucher_detail_voucher_id")
    op.execute("DROP INDEX IF EXISTS ix_pcdv_project_code_id")
