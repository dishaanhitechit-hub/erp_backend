"""MIS Boards: Kanban position on mis_tasks + per-project board config

Additive: three nullable / defaulted columns on mis_tasks and the table
mis_board_configs. Existing rows keep NULL column (= first column of their state).

Revision ID: 0b21b0d4b94c
Revises: a1d4efc911bd
Create Date: 2026-11-26 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '0b21b0d4b94c'
down_revision = 'a1d4efc911bd'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.add_column(sa.Column('board_column', sa.String(length=40), nullable=True))
        b.add_column(sa.Column('board_column_done', sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column('board_lane', sa.String(length=40), nullable=True))

    op.create_table(
        'mis_board_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('level', sa.String(length=10), nullable=False),
        sa.Column('columns', sa.JSON(), nullable=False),
        sa.Column('swimlanes', sa.JSON(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_mis_board_configs_project_id', 'mis_board_configs', ['project_id'])


def downgrade():
    op.drop_index('ix_mis_board_configs_project_id', table_name='mis_board_configs')
    op.drop_table('mis_board_configs')
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.drop_column('board_lane')
        b.drop_column('board_column_done')
        b.drop_column('board_column')
