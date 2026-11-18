"""register bank_statement in module_master

b5a7c1d9e3f2 added the 'bank_statement' feature page but not its module_master
row. approval_path.module_code is a FK to module_master, so saving creator /
approver settings for Bank Statements failed with ForeignKeyViolation.
Idempotent: skips the row if it already exists (e.g. inserted by hand).

Revision ID: c6d8e2f4a1b3
Revises: b5a7c1d9e3f2
Create Date: 2026-11-18 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c6d8e2f4a1b3'
down_revision = 'b5a7c1d9e3f2'
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text(
        """INSERT INTO module_master (module_code, module_name, status)
        SELECT 'bank_statement', 'Bank Statements', 'Active'
        WHERE NOT EXISTS (SELECT 1 FROM module_master WHERE module_code = 'bank_statement')"""
    ))


def downgrade():
    # Row kept on purpose: approval_path rows may reference it.
    pass
