"""MIS self task: mis_tasks, mis_activity + permission pages

Adds two new tables only (nothing existing is altered) and, if missing, the
permission pages `to_do_list` and `self_task_all` so super admin can grant
"view/edit everyone's tasks" per project in Settings → Role & Designation.

Revision ID: b1c2d3e4f5a6
Revises: e5fa07c3b924
Create Date: 2026-11-15 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'e5fa07c3b924'
branch_labels = None
depends_on = None


_PAGES = [
    # (page_code, page_name, route_path, menu_visible, sort)
    ("to_do_list", "Self Task", "/task-management/todo", True, 2),
    ("self_task_all", "Self Task – View/Edit All Users", None, False, 3),
]


def upgrade():
    op.create_table(
        'mis_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_uuid', sa.String(length=36), nullable=False),
        sa.Column('task_code', sa.String(length=30), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=False, server_default='Medium'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='To Do'),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('estimated_hours', sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column('actual_hours', sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column('reopen_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_code'),
    )
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.create_index(b.f('ix_mis_tasks_task_uuid'), ['task_uuid'], unique=True)
        b.create_index(b.f('ix_mis_tasks_owner_user_id'), ['owner_user_id'], unique=False)
        b.create_index(b.f('ix_mis_tasks_created_by'), ['created_by'], unique=False)
        b.create_index(b.f('ix_mis_tasks_project_id'), ['project_id'], unique=False)
        b.create_index(b.f('ix_mis_tasks_status'), ['status'], unique=False)
        b.create_index(b.f('ix_mis_tasks_due_date'), ['due_date'], unique=False)
        b.create_index(b.f('ix_mis_tasks_is_deleted'), ['is_deleted'], unique=False)

    op.create_table(
        'mis_activity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=30), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_mis_activity_entity', 'mis_activity', ['entity_type', 'entity_id'], unique=False)

    # ── permission pages (idempotent) ──────────────────────────────────
    # Put them next to an existing MIS page if there is one; otherwise create
    # a "MIS" main module + "Task Management" sub module for them.
    conn = op.get_bind()
    sub_id = conn.execute(sa.text(
        "SELECT submodule_id FROM feature_pages "
        "WHERE page_code IN ('to_do_list','task_tracker','schedule_compliance') "
        "ORDER BY id LIMIT 1")).scalar()
    if sub_id is None:
        mm_id = conn.execute(sa.text(
            "SELECT id FROM main_modules WHERE module_name = 'MIS'")).scalar()
        if mm_id is None:
            mm_id = conn.execute(sa.text(
                "INSERT INTO main_modules (module_name, icon) VALUES ('MIS', 'ListTodo') RETURNING id")).scalar()
        sub_id = conn.execute(sa.text(
            "SELECT id FROM sub_modules WHERE main_module_id = :m AND submodule_name = 'Task Management'"),
            {"m": mm_id}).scalar()
        if sub_id is None:
            sub_id = conn.execute(sa.text(
                "INSERT INTO sub_modules (main_module_id, submodule_name) "
                "VALUES (:m, 'Task Management') RETURNING id"), {"m": mm_id}).scalar()

    for code, name, path, visible, sort in _PAGES:
        conn.execute(sa.text(
            "INSERT INTO feature_pages (submodule_id, page_name, page_code, route_path, is_menu_visible, sort_order) "
            "SELECT :s, :n, :c, :p, :v, :o "
            "WHERE NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = :c)"),
            {"s": sub_id, "n": name, "c": code, "p": path, "v": visible, "o": sort})


def downgrade():
    # feature_pages / modules rows are kept on purpose (permissions may reference them)
    op.drop_index('ix_mis_activity_entity', table_name='mis_activity')
    op.drop_table('mis_activity')
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        for ix in ('is_deleted', 'due_date', 'status', 'project_id', 'created_by', 'owner_user_id', 'task_uuid'):
            b.drop_index(b.f(f'ix_mis_tasks_{ix}'))
    op.drop_table('mis_tasks')
