"""issue tracker: items, members, app_setting kill switch + issue_tracker page

  * app_setting          — key/value settings; 'issue_tracker.enabled' is the kill switch
  * issue_tracker_member — users allowed on the page (can_edit / is_developer)
  * issue_tracker_item   — issues / feature requests with the developer's done tick
  * feature_pages + module_master rows for 'issue_tracker' (idempotent)

Revision ID: d4f6b8c0e2a5
Revises: c3e5a7b9d1f4
Create Date: 2026-11-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4f6b8c0e2a5'
down_revision = 'c3e5a7b9d1f4'
branch_labels = None
depends_on = None

_PAGE = ("issue_tracker", "Issues & Requests", "/issue-tracker")


def upgrade():
    op.create_table(
        'app_setting',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_table(
        'issue_tracker_member',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('can_edit', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_developer', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('added_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('added_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_table(
        'issue_tracker_item',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(20), nullable=False, server_default='ISSUE'),
        sa.Column('body_html', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_done', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('done_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('done_at', sa.DateTime(), nullable=True),
        sa.Column('done_comment', sa.Text(), nullable=True),
        sa.Column('done_images', sa.JSON(), nullable=True),
        sa.CheckConstraint("kind IN ('ISSUE', 'FEATURE')", name='ck_issue_tracker_item_kind'),
    )
    op.create_index('ix_issue_tracker_item_is_done', 'issue_tracker_item', ['is_done'])

    # ── page code: own main module + sub module (idempotent) ──
    conn = op.get_bind()
    code, name, route = _PAGE
    main = conn.execute(sa.text("SELECT id FROM main_modules WHERE module_name = :n LIMIT 1"), {"n": name}).fetchone()
    main_id = main[0] if main else conn.execute(sa.text(
        "INSERT INTO main_modules (module_name, icon) VALUES (:n, 'Bug') RETURNING id"), {"n": name}).fetchone()[0]
    sub = conn.execute(sa.text(
        "SELECT id FROM sub_modules WHERE main_module_id = :mid AND submodule_name = :n LIMIT 1"),
        {"mid": main_id, "n": name}).fetchone()
    sub_id = sub[0] if sub else conn.execute(sa.text(
        "INSERT INTO sub_modules (main_module_id, submodule_name) VALUES (:mid, :n) RETURNING id"),
        {"mid": main_id, "n": name}).fetchone()[0]
    conn.execute(sa.text(
        """INSERT INTO feature_pages (submodule_id, page_name, page_code, route_path, is_menu_visible, sort_order)
        SELECT :sid, :name, :code, :route, TRUE, 99
        WHERE NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = :code)"""),
        {"sid": sub_id, "name": name, "code": code, "route": route})
    conn.execute(sa.text(
        """INSERT INTO module_master (module_code, module_name, status)
        SELECT :code, :name, 'Active'
        WHERE NOT EXISTS (SELECT 1 FROM module_master WHERE module_code = :code)"""),
        {"code": code, "name": name})


def downgrade():
    op.drop_index('ix_issue_tracker_item_is_done', table_name='issue_tracker_item')
    op.drop_table('issue_tracker_item')
    op.drop_table('issue_tracker_member')
    op.drop_table('app_setting')
    # feature_pages / module_master rows kept on purpose (approval_path may reference them)
