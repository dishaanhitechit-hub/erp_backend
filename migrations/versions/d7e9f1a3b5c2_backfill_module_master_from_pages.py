"""backfill module_master for every feature page that is missing

Saving Settings > Approval Path sends every page code, and approval_path has a
FK to module_master. Pages added after the original seed (self_task_all,
bank_statement, ...) only existed in feature_pages, so the save failed with
ForeignKeyViolation. This inserts the missing module_master rows (name = page
name). Idempotent; codes longer than module_master.module_code (50) are skipped.

Revision ID: d7e9f1a3b5c2
Revises: c6d8e2f4a1b3
Create Date: 2026-11-18 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd7e9f1a3b5c2'
down_revision = 'c6d8e2f4a1b3'
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text(
        """INSERT INTO module_master (module_code, module_name, status)
        SELECT DISTINCT ON (fp.page_code) fp.page_code, LEFT(COALESCE(fp.page_name, fp.page_code), 100), 'Active'
        FROM feature_pages fp
        WHERE fp.page_code IS NOT NULL
          AND LENGTH(fp.page_code) <= 50
          AND NOT EXISTS (SELECT 1 FROM module_master mm WHERE mm.module_code = fp.page_code)
        ORDER BY fp.page_code, fp.id"""
    ))


def downgrade():
    # Rows kept on purpose: approval_path rows may reference them.
    pass
