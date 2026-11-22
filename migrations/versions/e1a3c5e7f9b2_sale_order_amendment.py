"""sale order amendments (extra items on an approved order)

- og_sale_order_amendment         one row per amendment (AMD-1, AMD-2 …), own workflow
- og_sale_order_amendment_items   proposed lines, copied into the order on final approval
- og_sale_order_items.amendment_id / og_sale_order_boq_items.amendment_id
                                  set on lines added by an amendment (NULL = original line)
- module_master 'sale_order_amendment' (approval_history FK) + workflow alias to
  'sale_order', so an amendment uses the Sale Order's creators and approvers.

Revision ID: e1a3c5e7f9b2
Revises: d4f6b8c0e2a5
Create Date: 2026-11-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e1a3c5e7f9b2'
down_revision = 'd4f6b8c0e2a5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'og_sale_order_amendment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('og_sale_order_id', sa.Integer(),
                  sa.ForeignKey('og_sale_order_master.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amendment_seq', sa.Integer(), nullable=False),
        sa.Column('amendment_no', sa.String(60), nullable=False),
        sa.Column('amendment_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('customer_ref', sa.String(100), nullable=True),
        sa.Column('attachment', sa.Text(), nullable=True),
        sa.Column('project_code', sa.String(50), sa.ForeignKey('projects.project_code'), nullable=False),
        sa.Column('basic_amount', sa.Numeric(14, 2), server_default='0'),
        sa.Column('gst_amount', sa.Numeric(14, 2), server_default='0'),
        sa.Column('total_amount', sa.Numeric(14, 2), server_default='0'),
        sa.Column('order_total_before', sa.Numeric(14, 2), nullable=True),
        sa.Column('order_total_after', sa.Numeric(14, 2), nullable=True),
        sa.Column('workflow_status', sa.String(30), server_default='Draft'),
        sa.Column('current_level', sa.Integer(), server_default='0'),
        sa.Column('locked', sa.Boolean(), server_default=sa.false()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('updated_at', sa.DateTime()),
        sa.Column('submitted_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('submitted_at', sa.DateTime()),
        sa.Column('approved_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('final_approved_at', sa.DateTime()),
        sa.Column('rejected_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('rejected_at', sa.DateTime()),
        sa.Column('correction_sent_at', sa.DateTime()),
        sa.UniqueConstraint('og_sale_order_id', 'amendment_seq', name='uq_og_so_amendment_seq'),
    )
    op.create_index('ix_og_sale_order_amendment_og_sale_order_id', 'og_sale_order_amendment', ['og_sale_order_id'])

    op.create_table(
        'og_sale_order_amendment_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('amendment_id', sa.Integer(),
                  sa.ForeignKey('og_sale_order_amendment.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sl_no', sa.Integer(), nullable=False),
        sa.Column('item_type', sa.String(10), nullable=False, server_default='non-boq'),
        sa.Column('item_code', sa.String(50), nullable=True),
        sa.Column('item_name', sa.String(2000), nullable=True),
        sa.Column('item_description', sa.Text(), nullable=True),
        sa.Column('unit', sa.String(30), nullable=True),
        sa.Column('order_qty', sa.Numeric(17, 4), server_default='0'),
        sa.Column('rate', sa.Numeric(17, 4), server_default='0'),
        sa.Column('amount', sa.Numeric(14, 2), server_default='0'),
        sa.Column('gst_percent', sa.Numeric(5, 2), server_default='0'),
        sa.Column('gst_amount', sa.Numeric(14, 2), server_default='0'),
        sa.Column('so_item_id', sa.Integer(), nullable=True),
        sa.Column('so_item_sl_no', sa.Integer(), nullable=True),
    )
    op.create_index('ix_og_sale_order_amendment_items_amendment_id', 'og_sale_order_amendment_items', ['amendment_id'])

    for table in ('og_sale_order_items', 'og_sale_order_boq_items'):
        op.add_column(table, sa.Column('amendment_id', sa.Integer(), nullable=True))
        op.create_foreign_key(f'fk_{table}_amendment_id', table, 'og_sale_order_amendment',
                              ['amendment_id'], ['id'], ondelete='SET NULL')
        op.create_index(f'ix_{table}_amendment_id', table, ['amendment_id'])

    bind = op.get_bind()
    # Some rows in these tables were inserted with explicit ids, so their id
    # sequences can lag behind MAX(id) (seen on the server: duplicate key
    # workflow_module_alias_pkey id=3). Move each sequence past MAX(id) first.
    for table in ('module_master', 'workflow_module_alias'):
        bind.execute(sa.text(
            f"""SELECT setval(pg_get_serial_sequence('{table}', 'id'),
                              COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)
            WHERE pg_get_serial_sequence('{table}', 'id') IS NOT NULL"""
        ))
    bind.execute(sa.text(
        """INSERT INTO module_master (module_code, module_name, status)
        SELECT 'sale_order_amendment', 'Sale Order Amendment', 'Active'
        WHERE NOT EXISTS (SELECT 1 FROM module_master WHERE module_code = 'sale_order_amendment')"""
    ))
    bind.execute(sa.text(
        """INSERT INTO workflow_module_alias (module_code, approval_module_code)
        SELECT 'sale_order_amendment', 'sale_order'
        WHERE NOT EXISTS (SELECT 1 FROM workflow_module_alias WHERE module_code = 'sale_order_amendment')"""
    ))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM workflow_module_alias WHERE module_code = 'sale_order_amendment'"))
    for table in ('og_sale_order_boq_items', 'og_sale_order_items'):
        op.drop_index(f'ix_{table}_amendment_id', table_name=table)
        op.drop_constraint(f'fk_{table}_amendment_id', table, type_='foreignkey')
        op.drop_column(table, 'amendment_id')
    op.drop_index('ix_og_sale_order_amendment_items_amendment_id', table_name='og_sale_order_amendment_items')
    op.drop_table('og_sale_order_amendment_items')
    op.drop_index('ix_og_sale_order_amendment_og_sale_order_id', table_name='og_sale_order_amendment')
    op.drop_table('og_sale_order_amendment')
    # module_master row kept on purpose: approval_history rows reference it
