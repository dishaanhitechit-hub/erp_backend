"""permission page for MIS Boards → sprint_admin (data only)

Adds the permission-only `sprint_admin` feature page next to the other MIS pages
if it is missing, so super admin can grant "manage Boards sprints / capacity" per
project in Settings → Role & Designation.

Revision ID: bb1cd181a6b1
Revises: 95dfb3eac952
Create Date: 2026-11-26 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'bb1cd181a6b1'
down_revision = '95dfb3eac952'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    sub_id = conn.execute(sa.text(
        "SELECT submodule_id FROM feature_pages WHERE page_code IN ('to_do_list','task_tracker','self_task_all') "
        "ORDER BY id LIMIT 1")).scalar()
    if sub_id is not None:
        conn.execute(sa.text(
            "INSERT INTO feature_pages (submodule_id, page_name, page_code, route_path, is_menu_visible, sort_order) "
            "SELECT :s, 'Sprints – Manage (Boards)', 'sprint_admin', NULL, FALSE, 5 "
            "WHERE NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = 'sprint_admin')"), {"s": sub_id})


def downgrade():
    # kept on purpose (role permissions may reference it)
    pass
