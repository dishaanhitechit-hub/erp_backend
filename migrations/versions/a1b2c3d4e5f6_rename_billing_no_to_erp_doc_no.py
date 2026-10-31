"""rename billing_no to erp_no in billing_master and uncertain_allocation

Revision ID: a1b2c3d4e5f6
Revises: efd0fb041696
Create Date: 2026-10-31 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'efd0fb041696'
branch_labels = None
depends_on = None


def upgrade():
    # Step 1: rename existing erp_doc_no (OG Sale Order ref) to og_sale_order_erp_no
    op.alter_column('billing_master', 'erp_doc_no',
                    new_column_name='og_sale_order_erp_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)

    # Step 2: rename billing_no (system-gen bill number) to erp_no
    op.alter_column('billing_master', 'billing_no',
                    new_column_name='erp_no',
                    existing_type=sa.String(50),
                    existing_nullable=False)

    # Step 3: rename billing_no snapshot in uncertain_allocation to bill_erp_no
    op.alter_column('uncertain_allocation', 'billing_no',
                    new_column_name='bill_erp_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)

    # Step 4: rename erp_doc_no (OG Sale Order ref) in uncertain_allocation to erp_no
    op.alter_column('uncertain_allocation', 'erp_doc_no',
                    new_column_name='erp_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)

    # Step 5: rename erp_doc_no in og_sale_order_master to erp_no
    op.alter_column('og_sale_order_master', 'erp_doc_no',
                    new_column_name='erp_no',
                    existing_type=sa.String(50),
                    existing_nullable=False)

    # Step 6: rename erp_doc_no in sale_receipt_billing to erp_no
    op.alter_column('sale_receipt_billing', 'erp_doc_no',
                    new_column_name='erp_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)


def downgrade():
    op.alter_column('sale_receipt_billing', 'erp_no',
                    new_column_name='erp_doc_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)

    op.alter_column('og_sale_order_master', 'erp_no',
                    new_column_name='erp_doc_no',
                    existing_type=sa.String(50),
                    existing_nullable=False)

    op.alter_column('uncertain_allocation', 'erp_no',
                    new_column_name='erp_doc_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)

    op.alter_column('uncertain_allocation', 'bill_erp_no',
                    new_column_name='billing_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)

    op.alter_column('billing_master', 'erp_no',
                    new_column_name='billing_no',
                    existing_type=sa.String(50),
                    existing_nullable=False)

    op.alter_column('billing_master', 'og_sale_order_erp_no',
                    new_column_name='erp_doc_no',
                    existing_type=sa.String(50),
                    existing_nullable=True)
