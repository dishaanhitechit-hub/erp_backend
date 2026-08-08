"""qty_rate_numeric_17_4

Revision ID: b7c3d2e1f4a5
Revises: efde87db42ab
Create Date: 2026-08-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c3d2e1f4a5'
down_revision = 'efde87db42ab'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('grn_items', schema=None) as batch_op:
        batch_op.alter_column('order_qty',          existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('pre_received_qty',   existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('balance_qty',        existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('current_received_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('srn_items', schema=None) as batch_op:
        batch_op.alter_column('current_received_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('dc_items', schema=None) as batch_op:
        batch_op.alter_column('issue_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('gin_items', schema=None) as batch_op:
        batch_op.alter_column('issue_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.alter_column('qty',         existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('amend_qty',   existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('used_qty',    existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('balance_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('pw_order_items', schema=None) as batch_op:
        batch_op.alter_column('qty',         existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('amend_qty',   existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('used_qty',    existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('balance_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('brb_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('brg_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('brs_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('bvs_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('bss_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('billing_items', schema=None) as batch_op:
        batch_op.alter_column('claim_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',      existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('billing_boq_items', schema=None) as batch_op:
        batch_op.alter_column('claim_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',      existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('og_sale_order_items', schema=None) as batch_op:
        batch_op.alter_column('order_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',      existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('og_sale_order_boq_items', schema=None) as batch_op:
        batch_op.alter_column('order_qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)
        batch_op.alter_column('rate',      existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=True)

    with op.batch_alter_table('indent_items', schema=None) as batch_op:
        batch_op.alter_column('qty', existing_type=sa.Numeric(12,2), type_=sa.Numeric(17,4), existing_nullable=False)


def downgrade():
    with op.batch_alter_table('indent_items', schema=None) as batch_op:
        batch_op.alter_column('qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=False)

    with op.batch_alter_table('og_sale_order_boq_items', schema=None) as batch_op:
        batch_op.alter_column('order_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',      existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('og_sale_order_items', schema=None) as batch_op:
        batch_op.alter_column('order_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',      existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('billing_boq_items', schema=None) as batch_op:
        batch_op.alter_column('claim_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',      existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('billing_items', schema=None) as batch_op:
        batch_op.alter_column('claim_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',      existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('bss_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('bvs_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('brs_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('brg_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('brb_items', schema=None) as batch_op:
        batch_op.alter_column('billing_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('pw_order_items', schema=None) as batch_op:
        batch_op.alter_column('qty',         existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('amend_qty',   existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('used_qty',    existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('balance_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.alter_column('qty',         existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('amend_qty',   existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('used_qty',    existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('balance_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('rate',        existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('gin_items', schema=None) as batch_op:
        batch_op.alter_column('issue_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('dc_items', schema=None) as batch_op:
        batch_op.alter_column('issue_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('srn_items', schema=None) as batch_op:
        batch_op.alter_column('current_received_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)

    with op.batch_alter_table('grn_items', schema=None) as batch_op:
        batch_op.alter_column('order_qty',            existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('pre_received_qty',     existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('balance_qty',          existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
        batch_op.alter_column('current_received_qty', existing_type=sa.Numeric(17,4), type_=sa.Numeric(12,2), existing_nullable=True)
