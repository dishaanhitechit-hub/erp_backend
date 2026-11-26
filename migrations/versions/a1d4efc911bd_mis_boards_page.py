"""permission page for MIS → Boards (data only)

Adds the `mis_boards` feature page (menu: MIS → Boards) next to the other MIS
pages if it is missing, so super admin can grant it in Settings → Role & Designation.

Revision ID: a1d4efc911bd
Revises: bb1cd181a6b1
Create Date: 2026-11-26 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1d4efc911bd'
down_revision = 'bb1cd181a6b1'
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
            "SELECT :s, 'Boards', 'mis_boards', '/task-management/boards', TRUE, 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = 'mis_boards')"), {"s": sub_id})


def downgrade():
    # kept on purpose (role permissions may reference it)
    pass
