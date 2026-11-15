"""MIS follow-up board: mis_sprints, mis_followups, mis_followup_steps

Adds three new tables only (nothing existing is altered) and, if missing, the
`task_tracker` permission page (VIEW = see a project's board, EDIT = supervisor).

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-11-15 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def _ts():
    return [
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    ]


def upgrade():
    op.create_table(
        'mis_sprints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sprint_uuid', sa.String(length=36), nullable=False),
        sa.Column('sprint_code', sa.String(length=30), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('sprint_type', sa.String(length=10), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts(),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sprint_code'),
    )
    with op.batch_alter_table('mis_sprints', schema=None) as b:
        b.create_index(b.f('ix_mis_sprints_sprint_uuid'), ['sprint_uuid'], unique=True)
        b.create_index(b.f('ix_mis_sprints_status'), ['status'], unique=False)
        b.create_index(b.f('ix_mis_sprints_project_id'), ['project_id'], unique=False)

    op.create_table(
        'mis_followups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fu_uuid', sa.String(length=36), nullable=False),
        sa.Column('fu_code', sa.String(length=30), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=False),
        sa.Column('board_status', sa.String(length=20), nullable=False),
        sa.Column('story_points', sa.Integer(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('sprint_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('supervisor_user_id', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts(),
        sa.ForeignKeyConstraint(['sprint_id'], ['mis_sprints.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['supervisor_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fu_code'),
    )
    with op.batch_alter_table('mis_followups', schema=None) as b:
        b.create_index(b.f('ix_mis_followups_fu_uuid'), ['fu_uuid'], unique=True)
        b.create_index(b.f('ix_mis_followups_board_status'), ['board_status'], unique=False)
        b.create_index(b.f('ix_mis_followups_due_date'), ['due_date'], unique=False)
        b.create_index(b.f('ix_mis_followups_sprint_id'), ['sprint_id'], unique=False)
        b.create_index(b.f('ix_mis_followups_project_id'), ['project_id'], unique=False)
        b.create_index(b.f('ix_mis_followups_supervisor_user_id'), ['supervisor_user_id'], unique=False)
        b.create_index(b.f('ix_mis_followups_is_deleted'), ['is_deleted'], unique=False)

    op.create_table(
        'mis_followup_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('followup_id', sa.Integer(), nullable=False),
        sa.Column('seq_no', sa.Integer(), nullable=False),
        sa.Column('assignee_user_id', sa.Integer(), nullable=False),
        sa.Column('assigned_by', sa.Integer(), nullable=False),
        sa.Column('instruction', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('is_rework', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('assigned_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completion_note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['followup_id'], ['mis_followups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assignee_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('followup_id', 'seq_no', name='uq_mis_followup_step_seq'),
    )
    with op.batch_alter_table('mis_followup_steps', schema=None) as b:
        b.create_index(b.f('ix_mis_followup_steps_followup_id'), ['followup_id'], unique=False)
        b.create_index(b.f('ix_mis_followup_steps_assignee_user_id'), ['assignee_user_id'], unique=False)
        b.create_index(b.f('ix_mis_followup_steps_status'), ['status'], unique=False)

    # permission page next to the other MIS pages (created by b1c2d3e4f5a6)
    conn = op.get_bind()
    sub_id = conn.execute(sa.text(
        "SELECT submodule_id FROM feature_pages "
        "WHERE page_code IN ('to_do_list','self_task_all','schedule_compliance') ORDER BY id LIMIT 1")).scalar()
    if sub_id is not None:
        conn.execute(sa.text(
            "INSERT INTO feature_pages (submodule_id, page_name, page_code, route_path, is_menu_visible, sort_order) "
            "SELECT :s, 'Follow-up Board', 'task_tracker', '/task-management/task-tracker', TRUE, 1 "
            "WHERE NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = 'task_tracker')"), {"s": sub_id})


def downgrade():
    # the feature_pages row is kept on purpose (permissions may reference it)
    with op.batch_alter_table('mis_followup_steps', schema=None) as b:
        for ix in ('status', 'assignee_user_id', 'followup_id'):
            b.drop_index(b.f(f'ix_mis_followup_steps_{ix}'))
    op.drop_table('mis_followup_steps')
    with op.batch_alter_table('mis_followups', schema=None) as b:
        for ix in ('is_deleted', 'supervisor_user_id', 'project_id', 'sprint_id', 'due_date', 'board_status', 'fu_uuid'):
            b.drop_index(b.f(f'ix_mis_followups_{ix}'))
    op.drop_table('mis_followups')
    with op.batch_alter_table('mis_sprints', schema=None) as b:
        for ix in ('project_id', 'status', 'sprint_uuid'):
            b.drop_index(b.f(f'ix_mis_sprints_{ix}'))
    op.drop_table('mis_sprints')
