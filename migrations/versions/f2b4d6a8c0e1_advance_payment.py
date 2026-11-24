"""advance payment: ADVANCE payment requests (link to BRR / journal later)
and advance-type bill payments against them

Revision ID: f2b4d6a8c0e1
Revises: e1a3c5e7f9b2
Create Date: 2026-11-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2b4d6a8c0e1'
down_revision = 'e1a3c5e7f9b2'
branch_labels = None
depends_on = None


_OLD_CHECK = (
    "(source_type = 'BRR' AND brr_id IS NOT NULL AND journal_id IS NULL) OR "
    "(source_type = 'JOURNAL' AND journal_id IS NOT NULL AND brr_id IS NULL AND vendor_id IS NOT NULL)"
)
_NEW_CHECK = (
    _OLD_CHECK + " OR "
    "(source_type = 'ADVANCE' AND vendor_id IS NOT NULL AND (brr_id IS NULL OR journal_id IS NULL))"
)


def upgrade():
    with op.batch_alter_table('payment_request_master', schema=None) as batch_op:
        batch_op.add_column(sa.Column('link_type', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('linked_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('linked_by', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_payment_request_linked_by', 'users', ['linked_by'], ['id'])
        batch_op.drop_constraint('ck_payment_request_source', type_='check')
        batch_op.create_check_constraint('ck_payment_request_source', _NEW_CHECK)

    with op.batch_alter_table('bill_payment_receipt_master', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_request_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_bpr_payment_request_id', 'payment_request_master', ['payment_request_id'], ['id']
        )
        batch_op.create_index(
            batch_op.f('ix_bill_payment_receipt_master_payment_request_id'), ['payment_request_id'], unique=False
        )


def downgrade():
    # Advance rows cannot satisfy the old check — remove them first.
    op.execute("DELETE FROM bill_payment_receipt_master WHERE payment_type = 'advance'")
    with op.batch_alter_table('bill_payment_receipt_master', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bill_payment_receipt_master_payment_request_id'))
        batch_op.drop_constraint('fk_bpr_payment_request_id', type_='foreignkey')
        batch_op.drop_column('payment_request_id')

    op.execute("DELETE FROM payment_request_master WHERE source_type = 'ADVANCE'")
    with op.batch_alter_table('payment_request_master', schema=None) as batch_op:
        batch_op.drop_constraint('ck_payment_request_source', type_='check')
        batch_op.create_check_constraint('ck_payment_request_source', _OLD_CHECK)
        batch_op.drop_constraint('fk_payment_request_linked_by', type_='foreignkey')
        batch_op.drop_column('linked_by')
        batch_op.drop_column('linked_at')
        batch_op.drop_column('link_type')
