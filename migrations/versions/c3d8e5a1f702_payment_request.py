"""payment request against BRR

Revision ID: c3d8e5a1f702
Revises: a7c3e1d2b9f0
Create Date: 2026-11-14 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d8e5a1f702'
down_revision = 'a7c3e1d2b9f0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment_request_master',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pr_no', sa.String(length=50), nullable=False),
        sa.Column('pr_date', sa.Date(), nullable=False),
        sa.Column('pr_uuid', sa.String(length=36), nullable=True),
        sa.Column('project_code', sa.String(length=50), nullable=False),
        sa.Column('brr_id', sa.Integer(), nullable=False),
        sa.Column('brr_no', sa.String(length=50), nullable=True),
        sa.Column('vendor_id', sa.Integer(), nullable=True),
        sa.Column('order_category', sa.String(length=100), nullable=True),
        sa.Column('party_bill_no', sa.String(length=100), nullable=True),
        sa.Column('party_date', sa.Date(), nullable=True),
        sa.Column('bill_amount', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('previously_requested', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('requested_amount', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('deduction_amount', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('deduction_remarks', sa.String(length=500), nullable=True),
        sa.Column('net_payable', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('payment_mode', sa.String(length=30), nullable=True),
        sa.Column('required_by_date', sa.Date(), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('attached_doc', sa.String(length=500), nullable=True),
        sa.Column('workflow_status', sa.String(length=30), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('current_level', sa.Integer(), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('submitted_by', sa.Integer(), nullable=True),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('rejected_by', sa.Integer(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('final_approved_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('correction_sent_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_code'], ['projects.project_code'], ),
        sa.ForeignKeyConstraint(['brr_id'], ['brr_master.id'], ),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['submitted_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['rejected_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pr_no'),
        sa.UniqueConstraint('pr_uuid'),
    )
    with op.batch_alter_table('payment_request_master', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payment_request_master_brr_id'), ['brr_id'], unique=False)

    # Permission page "payment_request" under the same sub-module as BRR
    # (Sub Contractor Billing). Idempotent: skipped if it already exists or
    # if the BRR page is missing.
    op.execute(
        """
        INSERT INTO feature_pages (submodule_id, page_name, page_code, route_path, is_menu_visible, sort_order)
        SELECT fp.submodule_id,
               'Payment Request',
               'payment_request',
               '/resource-management/sub-contractor-billing/payment-request',
               TRUE,
               COALESCE(fp.sort_order, 0) + 1
        FROM feature_pages fp
        WHERE fp.page_code = 'bill_receive_register'
          AND NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = 'payment_request')
        LIMIT 1
        """
    )


def downgrade():
    # feature_pages row is intentionally kept (permissions may reference it)
    with op.batch_alter_table('payment_request_master', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payment_request_master_brr_id'))
    op.drop_table('payment_request_master')
