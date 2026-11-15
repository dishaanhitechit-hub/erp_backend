"""MIS self task: work timer, start/due times, Done lock + reopen requests

Adds columns to mis_tasks (all nullable or with a default — existing rows are
untouched) and the new table mis_task_reopen_requests.

Revision ID: 6276fc8b7528
Revises: 1dc8a8e6356c
Create Date: 2026-11-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '6276fc8b7528'
down_revision = '1dc8a8e6356c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.add_column(sa.Column('start_time', sa.Time(), nullable=True))
        b.add_column(sa.Column('due_time', sa.Time(), nullable=True))
        b.add_column(sa.Column('started_at', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('run_started_at', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('worked_seconds', sa.Integer(), nullable=False, server_default='0'))

    op.create_table(
        'mis_task_reopen_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('requested_by', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('decided_by', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['mis_tasks.id']),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id']),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('mis_task_reopen_requests', schema=None) as b:
        b.create_index(b.f('ix_mis_task_reopen_requests_task_id'), ['task_id'], unique=False)
        b.create_index(b.f('ix_mis_task_reopen_requests_status'), ['status'], unique=False)


def downgrade():
    with op.batch_alter_table('mis_task_reopen_requests', schema=None) as b:
        b.drop_index(b.f('ix_mis_task_reopen_requests_status'))
        b.drop_index(b.f('ix_mis_task_reopen_requests_task_id'))
    op.drop_table('mis_task_reopen_requests')
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.drop_column('worked_seconds')
        b.drop_column('run_started_at')
        b.drop_column('started_at')
        b.drop_column('due_time')
        b.drop_column('start_time')
