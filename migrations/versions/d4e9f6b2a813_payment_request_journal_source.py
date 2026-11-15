"""payment request: journal entry as source + restricted permission page

Revision ID: d4e9f6b2a813
Revises: c3d8e5a1f702
Create Date: 2026-11-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e9f6b2a813'
down_revision = 'c3d8e5a1f702'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payment_request_master', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_type', sa.String(length=20), nullable=False, server_default='BRR'))
        batch_op.add_column(sa.Column('journal_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('journal_voucher_no', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('journal_date', sa.Date(), nullable=True))
        batch_op.alter_column('brr_id', existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(
            'fk_payment_request_journal_id', 'journal_entry_master', ['journal_id'], ['id']
        )
        batch_op.create_index(batch_op.f('ix_payment_request_master_journal_id'), ['journal_id'], unique=False)
        batch_op.create_check_constraint(
            'ck_payment_request_source',
            "(source_type = 'BRR' AND brr_id IS NOT NULL AND journal_id IS NULL) OR "
            "(source_type = 'JOURNAL' AND journal_id IS NOT NULL AND brr_id IS NULL AND vendor_id IS NOT NULL)",
        )

    # Restricted permission page — granted by super admin in
    # Settings › Roles & User Assignment. Same sub-module as BRR. Idempotent.
    op.execute(
        """
        INSERT INTO feature_pages (submodule_id, page_name, page_code, route_path, is_menu_visible, sort_order)
        SELECT fp.submodule_id,
               'Payment Request - Journal',
               'payment_request_journal',
               NULL,
               FALSE,
               COALESCE(fp.sort_order, 0) + 1
        FROM feature_pages fp
        WHERE fp.page_code = 'payment_request'
          AND NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = 'payment_request_journal')
        LIMIT 1
        """
    )


def downgrade():
    # Journal-sourced rows cannot satisfy NOT NULL brr_id — remove them first.
    op.execute("DELETE FROM payment_request_master WHERE source_type = 'JOURNAL'")
    with op.batch_alter_table('payment_request_master', schema=None) as batch_op:
        batch_op.drop_constraint('ck_payment_request_source', type_='check')
        batch_op.drop_index(batch_op.f('ix_payment_request_master_journal_id'))
        batch_op.drop_constraint('fk_payment_request_journal_id', type_='foreignkey')
        batch_op.alter_column('brr_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('journal_date')
        batch_op.drop_column('journal_voucher_no')
        batch_op.drop_column('journal_id')
        batch_op.drop_column('source_type')
    # feature_pages row is intentionally kept (permissions may reference it)
