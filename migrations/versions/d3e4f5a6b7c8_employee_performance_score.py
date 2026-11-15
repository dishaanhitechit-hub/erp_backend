"""employee_performance_scores (saved weekly / monthly performance scores)

New table only — nothing existing is altered.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-11-15 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'employee_performance_scores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subject_key', sa.String(length=30), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('period_type', sa.String(length=10), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('score', sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column('grade', sa.String(length=30), nullable=True),
        sa.Column('components', sa.JSON(), nullable=True),
        sa.Column('computed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subject_key', 'period_type', 'period_start', name='uq_perf_score_subject_period'),
    )
    with op.batch_alter_table('employee_performance_scores', schema=None) as b:
        b.create_index(b.f('ix_employee_performance_scores_employee_id'), ['employee_id'], unique=False)
        b.create_index(b.f('ix_employee_performance_scores_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('employee_performance_scores', schema=None) as b:
        b.drop_index(b.f('ix_employee_performance_scores_user_id'))
        b.drop_index(b.f('ix_employee_performance_scores_employee_id'))
    op.drop_table('employee_performance_scores')
