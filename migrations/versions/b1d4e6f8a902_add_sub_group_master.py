"""add sub_group_master and cc_codes.sub_group_id

Revision ID: b1d4e6f8a902
Revises: a7c3e91d2b40
Create Date: 2026-11-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b1d4e6f8a902'
down_revision = 'a7c3e91d2b40'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sub_group_master',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fixed_code', sa.String(length=50), nullable=False),
        sa.Column('sub_group_name', sa.String(length=150), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['group_id'], ['group_master.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fixed_code'),
        sa.UniqueConstraint('group_id', 'sub_group_name', name='uq_sub_group_group_name'),
    )
    with op.batch_alter_table('cc_codes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sub_group_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_cc_codes_sub_group_id', 'sub_group_master', ['sub_group_id'], ['id'])


def downgrade():
    with op.batch_alter_table('cc_codes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cc_codes_sub_group_id', type_='foreignkey')
        batch_op.drop_column('sub_group_id')
    op.drop_table('sub_group_master')
