"""sub group levels: parent_id + level, unique name per parent

Revision ID: c3f7a9d1e204
Revises: b1d4e6f8a902
Create Date: 2026-11-01 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3f7a9d1e204'
down_revision = 'b1d4e6f8a902'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sub_group_master', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('level', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_foreign_key('fk_sub_group_parent_id', 'sub_group_master', ['parent_id'], ['id'])
        batch_op.drop_constraint('uq_sub_group_group_name', type_='unique')
        batch_op.create_unique_constraint('uq_sub_group_parent_name', ['group_id', 'parent_id', 'sub_group_name'])
    # existing codes -> uppercase
    op.execute("UPDATE sub_group_master SET fixed_code = UPPER(fixed_code)")


def downgrade():
    with op.batch_alter_table('sub_group_master', schema=None) as batch_op:
        batch_op.drop_constraint('uq_sub_group_parent_name', type_='unique')
        batch_op.create_unique_constraint('uq_sub_group_group_name', ['group_id', 'sub_group_name'])
        batch_op.drop_constraint('fk_sub_group_parent_id', type_='foreignkey')
        batch_op.drop_column('level')
        batch_op.drop_column('parent_id')
