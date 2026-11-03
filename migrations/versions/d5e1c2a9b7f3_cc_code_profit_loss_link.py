"""cc_codes: optional Profit & Loss link (pl_linked, pl_group_id, pl_sub_group_id)

Every CC code sits in a Balance Sheet group; some also fall under Profit & Loss.

Revision ID: d5e1c2a9b7f3
Revises: 22bbe4985ece
Create Date: 2026-11-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e1c2a9b7f3'
down_revision = '22bbe4985ece'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cc_codes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pl_linked', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('pl_group_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pl_sub_group_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_cc_codes_pl_group_id', 'group_master', ['pl_group_id'], ['id'])
        batch_op.create_foreign_key('fk_cc_codes_pl_sub_group_id', 'sub_group_master', ['pl_sub_group_id'], ['id'])


def downgrade():
    with op.batch_alter_table('cc_codes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cc_codes_pl_sub_group_id', type_='foreignkey')
        batch_op.drop_constraint('fk_cc_codes_pl_group_id', type_='foreignkey')
        batch_op.drop_column('pl_sub_group_id')
        batch_op.drop_column('pl_group_id')
        batch_op.drop_column('pl_linked')
