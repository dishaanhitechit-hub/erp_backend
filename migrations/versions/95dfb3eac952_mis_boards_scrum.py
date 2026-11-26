"""MIS Boards (Azure Boards style, Scrum): work item fields on mis_tasks + links,
sprint capacity, sprint snapshots, retro items, saved queries

Additive only. Existing mis_tasks rows become work_item_type = 'Task' with no
parent and no sprint, so the Self Task page and the performance score are
unchanged. backlog_rank is backfilled from id (oldest first).

Revision ID: 95dfb3eac952
Revises: c9e1f3a5b7d2
Create Date: 2026-11-26 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '95dfb3eac952'
down_revision = 'c9e1f3a5b7d2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.add_column(sa.Column('work_item_type', sa.String(length=10), nullable=False, server_default='Task'))
        b.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('sprint_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('story_points', sa.Numeric(5, 1), nullable=True))
        b.add_column(sa.Column('remaining_hours', sa.Numeric(7, 2), nullable=True))
        b.add_column(sa.Column('acceptance_criteria', sa.Text(), nullable=True))
        b.add_column(sa.Column('backlog_rank', sa.Float(), nullable=True))
        b.add_column(sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column('blocked_reason', sa.Text(), nullable=True))
        b.create_foreign_key('fk_mis_tasks_parent_id', 'mis_tasks', ['parent_id'], ['id'])
        b.create_foreign_key('fk_mis_tasks_sprint_id', 'mis_sprints', ['sprint_id'], ['id'])
        b.create_index(b.f('ix_mis_tasks_work_item_type'), ['work_item_type'], unique=False)
        b.create_index(b.f('ix_mis_tasks_parent_id'), ['parent_id'], unique=False)
        b.create_index(b.f('ix_mis_tasks_sprint_id'), ['sprint_id'], unique=False)
        b.create_index(b.f('ix_mis_tasks_backlog_rank'), ['backlog_rank'], unique=False)

    # backfill: keep today's order on the backlog (oldest first)
    op.execute("UPDATE mis_tasks SET backlog_rank = id * 1000.0 WHERE backlog_rank IS NULL")

    op.create_table(
        'mis_work_item_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('work_item_id', sa.Integer(), nullable=False),
        sa.Column('target_type', sa.String(length=12), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('target_ref', sa.String(length=120), nullable=True),
        sa.Column('link_type', sa.String(length=12), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['work_item_id'], ['mis_tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('work_item_id', 'target_type', 'target_id', 'target_ref', 'link_type',
                            name='uq_mis_wi_link'),
    )
    op.create_index('ix_mis_work_item_links_work_item_id', 'mis_work_item_links', ['work_item_id'])
    op.create_index('ix_mis_wi_links_target', 'mis_work_item_links', ['target_type', 'target_id'])

    op.create_table(
        'mis_sprint_capacity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sprint_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('hours_per_day', sa.Numeric(4, 1), nullable=False),
        sa.Column('days_off', sa.JSON(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['sprint_id'], ['mis_sprints.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sprint_id', 'user_id', name='uq_mis_sprint_capacity'),
    )
    op.create_index('ix_mis_sprint_capacity_sprint_id', 'mis_sprint_capacity', ['sprint_id'])
    op.create_index('ix_mis_sprint_capacity_user_id', 'mis_sprint_capacity', ['user_id'])

    op.create_table(
        'mis_sprint_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sprint_id', sa.Integer(), nullable=False),
        sa.Column('snap_date', sa.Date(), nullable=False),
        sa.Column('remaining_hours', sa.Numeric(9, 2), nullable=False),
        sa.Column('committed_points', sa.Numeric(7, 1), nullable=False),
        sa.Column('done_points', sa.Numeric(7, 1), nullable=False),
        sa.Column('state_counts', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['sprint_id'], ['mis_sprints.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sprint_id', 'snap_date', name='uq_mis_sprint_snapshot_day'),
    )
    op.create_index('ix_mis_sprint_snapshots_sprint_id', 'mis_sprint_snapshots', ['sprint_id'])

    op.create_table(
        'mis_retro_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sprint_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=12), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('work_item_id', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['sprint_id'], ['mis_sprints.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.ForeignKeyConstraint(['work_item_id'], ['mis_tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_mis_retro_items_sprint_id', 'mis_retro_items', ['sprint_id'])

    op.create_table(
        'mis_saved_queries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('filters', sa.JSON(), nullable=False),
        sa.Column('columns', sa.JSON(), nullable=True),
        sa.Column('is_shared', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_mis_saved_queries_owner_user_id', 'mis_saved_queries', ['owner_user_id'])
    op.create_index('ix_mis_saved_queries_project_id', 'mis_saved_queries', ['project_id'])


def downgrade():
    op.drop_index('ix_mis_saved_queries_project_id', table_name='mis_saved_queries')
    op.drop_index('ix_mis_saved_queries_owner_user_id', table_name='mis_saved_queries')
    op.drop_table('mis_saved_queries')
    op.drop_index('ix_mis_retro_items_sprint_id', table_name='mis_retro_items')
    op.drop_table('mis_retro_items')
    op.drop_index('ix_mis_sprint_snapshots_sprint_id', table_name='mis_sprint_snapshots')
    op.drop_table('mis_sprint_snapshots')
    op.drop_index('ix_mis_sprint_capacity_user_id', table_name='mis_sprint_capacity')
    op.drop_index('ix_mis_sprint_capacity_sprint_id', table_name='mis_sprint_capacity')
    op.drop_table('mis_sprint_capacity')
    op.drop_index('ix_mis_wi_links_target', table_name='mis_work_item_links')
    op.drop_index('ix_mis_work_item_links_work_item_id', table_name='mis_work_item_links')
    op.drop_table('mis_work_item_links')
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.drop_index(b.f('ix_mis_tasks_backlog_rank'))
        b.drop_index(b.f('ix_mis_tasks_sprint_id'))
        b.drop_index(b.f('ix_mis_tasks_parent_id'))
        b.drop_index(b.f('ix_mis_tasks_work_item_type'))
        b.drop_constraint('fk_mis_tasks_sprint_id', type_='foreignkey')
        b.drop_constraint('fk_mis_tasks_parent_id', type_='foreignkey')
        b.drop_column('blocked_reason')
        b.drop_column('is_blocked')
        b.drop_column('backlog_rank')
        b.drop_column('acceptance_criteria')
        b.drop_column('remaining_hours')
        b.drop_column('story_points')
        b.drop_column('sprint_id')
        b.drop_column('parent_id')
        b.drop_column('work_item_type')
