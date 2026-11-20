"""reback requests (send back a fully approved record, accepted by final approver / admin)

Revision ID: a1c3e5b7d9f2
Revises: 6193fafeeb4a
Create Date: 2026-11-20 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c3e5b7d9f2'
down_revision = '6193fafeeb4a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'reback_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('module', sa.String(length=50), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('record_no', sa.String(length=100), nullable=True),
        sa.Column('project_code', sa.String(length=50), nullable=True),
        sa.Column('approval_module', sa.String(length=50), nullable=True),
        sa.Column('page_url', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('requested_by', sa.Integer(), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('decided_by', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('decision_comment', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['project_code'], ['projects.project_code']),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id']),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reback_requests_module', 'reback_requests', ['module'])
    op.create_index('ix_reback_requests_project_code', 'reback_requests', ['project_code'])
    op.create_index('ix_reback_requests_status', 'reback_requests', ['status'])
    op.create_index('ix_reback_request_record', 'reback_requests', ['module', 'record_id'])
    op.create_index('uq_reback_request_open', 'reback_requests', ['module', 'record_id'], unique=True,
                    postgresql_where=sa.text("status = 'PENDING'"))


def downgrade():
    op.drop_index('uq_reback_request_open', table_name='reback_requests')
    op.drop_index('ix_reback_request_record', table_name='reback_requests')
    op.drop_index('ix_reback_requests_status', table_name='reback_requests')
    op.drop_index('ix_reback_requests_project_code', table_name='reback_requests')
    op.drop_index('ix_reback_requests_module', table_name='reback_requests')
    op.drop_table('reback_requests')
