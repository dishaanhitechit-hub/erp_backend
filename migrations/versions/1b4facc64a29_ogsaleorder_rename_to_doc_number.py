"""ogsaleorder rename to doc number

Revision ID: 1b4facc64a29
Revises: 3594a8ff06df
Create Date: 2026-10-31 13:11:32.940979

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1b4facc64a29'
down_revision = '3594a8ff06df'
branch_labels = None
depends_on = None


def upgrade():
    # Rename columns in-place to preserve existing data
    op.alter_column('billing_master', 'og_sale_order_no', new_column_name='erp_doc_no')
    op.alter_column('og_sale_order_master', 'og_sale_order_no', new_column_name='erp_doc_no')
    op.alter_column('sale_receipt_billing', 'og_sale_order_no', new_column_name='erp_doc_no')
    op.alter_column('uncertain_allocation_lines', 'og_sale_order_no', new_column_name='erp_doc_no')

    with op.batch_alter_table('comm_call_signals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_comm_call_signals_to_user_id'))
        batch_op.create_index(batch_op.f('ix_comm_call_signals_receiver_id'), ['receiver_id'], unique=False)


def downgrade():
    op.alter_column('uncertain_allocation_lines', 'erp_doc_no', new_column_name='og_sale_order_no')
    op.alter_column('sale_receipt_billing', 'erp_doc_no', new_column_name='og_sale_order_no')
    op.alter_column('og_sale_order_master', 'erp_doc_no', new_column_name='og_sale_order_no')
    op.alter_column('billing_master', 'erp_doc_no', new_column_name='og_sale_order_no')

    with op.batch_alter_table('comm_call_signals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_comm_call_signals_receiver_id'))
        batch_op.create_index(batch_op.f('ix_comm_call_signals_to_user_id'), ['receiver_id'], unique=False)
