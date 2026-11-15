"""permission page for MIS → Schedule Compliance (data only)

Adds the `schedule_compliance` feature page next to the other MIS pages if it
is missing, so super admin can grant it in Settings → Role & Designation.

Revision ID: 1dc8a8e6356c
Revises: d3e4f5a6b7c8
Create Date: 2026-11-16 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '1dc8a8e6356c'
down_revision = 'd3e4f5a6b7c8'
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
            "SELECT :s, 'Schedule Compliance', 'schedule_compliance', '/task-management/schedule-compliance', TRUE, 4 "
            "WHERE NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = 'schedule_compliance')"), {"s": sub_id})


def downgrade():
    # kept on purpose (role permissions may reference it)
    pass
