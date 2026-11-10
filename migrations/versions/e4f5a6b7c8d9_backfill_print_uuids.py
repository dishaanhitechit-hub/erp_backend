"""backfill print uuids

Older records were created before their print id (…_uuid) existed, so they
have none and can't open their print page (web Download / app document view).
Give every such record a new random id. Records that already have one are not
touched. Safe to run more than once.

Revision ID: e4f5a6b7c8d9
Revises: 96d609324057
Create Date: 2026-11-09 22:00:00

"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = 'e4f5a6b7c8d9'
down_revision = '96d609324057'
branch_labels = None
depends_on = None

# (table, uuid column) — every document with a print page
TABLES = [
    ('batching_plant_master', 'bp_uuid'),
    ('bbs_register', 'bbs_uuid'),
    ('bill_payment_receipt_master', 'receipt_uuid'),
    ('billing_master', 'billing_uuid'),
    ('brb_master', 'brb_uuid'),
    ('brr_master', 'brr_uuid'),
    ('budget_master', 'budget_uuid'),
    ('contra_entry_master', 'contra_uuid'),
    ('credit_note_master', 'credit_note_uuid'),
    ('debit_note_master', 'debit_note_uuid'),
    ('gin_master', 'gin_uuid'),
    ('grn_master', 'grn_uuid'),
    ('hindrance_register', 'hindrance_uuid'),
    ('indent_master', 'indent_uuid'),
    ('journal_entry_master', 'journal_uuid'),
    ('og_sale_order_master', 'og_sale_order_uuid'),
    ('order_master', 'order_uuid'),
    ('payment_voucher_master', 'payment_vouch_uuid'),
    ('petty_cash_budget', 'budget_uuid'),
    ('petty_cash_docket_voucher', 'voucher_uuid'),
    ('petty_cash_journal_voucher', 'voucher_uuid'),
    ('purchase_bill_master', 'purchase_bill_uuid'),
    ('pw_order_master', 'order_uuid'),
    ('sale_bill_master', 'sale_bill_uuid'),
    ('sale_receipt_billing', 'srb_uuid'),
    ('sale_receipt_master', 'receipt_uuid'),
    ('srn_master', 'srn_uuid'),
    ('uncertain_allocation_master', 'ua_uuid'),
    ('vendors', 'vendor_uuid'),
]


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing = set(insp.get_table_names())
    for table, col in TABLES:
        if table not in existing:
            continue
        cols = {c['name'] for c in insp.get_columns(table)}
        if col not in cols or 'id' not in cols:
            continue
        ids = [r[0] for r in conn.execute(sa.text(
            f'SELECT id FROM "{table}" WHERE "{col}" IS NULL OR "{col}" = \'\''
        ))]
        for rid in ids:
            conn.execute(
                sa.text(f'UPDATE "{table}" SET "{col}" = :u WHERE id = :id'),
                {'u': str(uuid.uuid4()), 'id': rid},
            )
        if ids:
            print(f'backfill print uuids: {table}.{col} — {len(ids)} record(s)')


def downgrade():
    # Ids handed out here may already be in shared links / QR codes — keep them.
    pass
