"""advance adjustment: settle a vendor's outstanding advance against bills
(purchase bill / journal), product-wise lines

Revision ID: a7c9e1b3d5f2
Revises: f2b4d6a8c0e1
Create Date: 2026-11-25 10:00:00.000000

Existing advances that were LINKED to a BRR / journal (old model) are turned
into adjustments by `python scripts/convert_advance_links.py` (needs app code
for the ledger re-post), run once after this migration.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c9e1b3d5f2'
down_revision = 'f2b4d6a8c0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'advance_adjustment_master',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('adjustment_no', sa.String(length=50), nullable=False),
        sa.Column('adjustment_uuid', sa.String(length=36), nullable=True),
        sa.Column('adjustment_date', sa.Date(), nullable=False),
        sa.Column('project_code', sa.String(length=50), sa.ForeignKey('projects.project_code'), nullable=False),
        sa.Column('vendor_id', sa.Integer(), sa.ForeignKey('vendors.id'), nullable=False),
        sa.Column('payment_request_id', sa.Integer(), sa.ForeignKey('payment_request_master.id'), nullable=False),
        sa.Column('link_type', sa.String(length=20), nullable=False),
        sa.Column('purchase_bill_id', sa.Integer(), sa.ForeignKey('purchase_bill_master.id'), nullable=True),
        sa.Column('brr_id', sa.Integer(), sa.ForeignKey('brr_master.id'), nullable=True),
        sa.Column('journal_id', sa.Integer(), sa.ForeignKey('journal_entry_master.id'), nullable=True),
        sa.Column('bill_no', sa.String(length=100), nullable=True),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('workflow_status', sa.String(length=30), nullable=False, server_default='Approved'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancel_reason', sa.Text(), nullable=True),
        sa.UniqueConstraint('adjustment_no', name='uq_advance_adjustment_no'),
        sa.UniqueConstraint('adjustment_uuid', name='uq_advance_adjustment_uuid'),
        sa.CheckConstraint(
            "workflow_status = 'Cancelled' OR "   # a deleted bill clears a cancelled adjustment's link
            "(link_type = 'BRR' AND purchase_bill_id IS NOT NULL AND journal_id IS NULL) OR "
            "(link_type = 'JOURNAL' AND journal_id IS NOT NULL AND purchase_bill_id IS NULL)",
            name='ck_advance_adjustment_link',
        ),
    )
    for col in ('project_code', 'vendor_id', 'payment_request_id', 'purchase_bill_id', 'brr_id', 'journal_id'):
        op.create_index(f'ix_advance_adjustment_master_{col}', 'advance_adjustment_master', [col])

    op.create_table(
        'advance_adjustment_line',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('adjustment_id', sa.Integer(),
                  sa.ForeignKey('advance_adjustment_master.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sl_no', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('line_type', sa.String(length=10), nullable=False),
        sa.Column('pb_item_id', sa.Integer(), sa.ForeignKey('purchase_bill_items.id'), nullable=True),
        sa.Column('gst_type', sa.String(length=30), nullable=True),
        sa.Column('je_line_id', sa.Integer(), sa.ForeignKey('journal_entry_lines.id'), nullable=True),
        sa.Column('cc_code', sa.String(length=50), nullable=True),
        sa.Column('cc_name', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('booked_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False, server_default='0'),
    )
    for col in ('adjustment_id', 'pb_item_id', 'je_line_id'):
        op.create_index(f'ix_advance_adjustment_line_{col}', 'advance_adjustment_line', [col])


def downgrade():
    op.drop_table('advance_adjustment_line')
    op.drop_table('advance_adjustment_master')
