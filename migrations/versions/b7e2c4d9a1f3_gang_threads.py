"""gang tracker conversations (threads + entries); member mobile optional

Revision ID: b7e2c4d9a1f3
Revises: 1f1d01e57404
Create Date: 2026-11-27 13:10:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e2c4d9a1f3'
down_revision = '1f1d01e57404'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('gang_members', 'mobile', existing_type=sa.String(length=20), nullable=True)

    op.create_table('gang_threads',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('topic', sa.String(length=300), nullable=False),
    sa.Column('project', sa.String(length=200), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False, server_default='Ongoing'),
    sa.Column('started_with_id', sa.Integer(), nullable=True),
    sa.Column('next_member_id', sa.Integer(), nullable=True),
    sa.Column('next_followup_date', sa.Date(), nullable=True),
    sa.Column('next_action', sa.String(length=300), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['started_with_id'], ['gang_members.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['next_member_id'], ['gang_members.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('gang_thread_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('member_id', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('referred_to_id', sa.Integer(), nullable=True),
    sa.Column('next_member_id', sa.Integer(), nullable=True),
    sa.Column('next_followup_date', sa.Date(), nullable=True),
    sa.Column('next_action', sa.String(length=300), nullable=True),
    sa.Column('status_after', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['thread_id'], ['gang_threads.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['member_id'], ['gang_members.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['referred_to_id'], ['gang_members.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['next_member_id'], ['gang_members.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gang_thread_entries_thread_id', 'gang_thread_entries', ['thread_id'])


def downgrade():
    op.drop_index('ix_gang_thread_entries_thread_id', table_name='gang_thread_entries')
    op.drop_table('gang_thread_entries')
    op.drop_table('gang_threads')
    op.execute("UPDATE gang_members SET mobile = '' WHERE mobile IS NULL")
    op.alter_column('gang_members', 'mobile', existing_type=sa.String(length=20), nullable=False)
