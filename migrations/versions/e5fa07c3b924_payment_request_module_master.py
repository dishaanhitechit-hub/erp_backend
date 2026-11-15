"""register payment request approval modules in module_master

approval_path.module_code has a FK to module_master.module_code, so every
approval-path module code must exist there before an approval path can be
saved for it.

Revision ID: e5fa07c3b924
Revises: d4e9f6b2a813
Create Date: 2026-11-15 18:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e5fa07c3b924'
down_revision = 'd4e9f6b2a813'
branch_labels = None
depends_on = None


_MODULES = [
    ("payment_request",         "Payment Request"),
    ("payment_request_journal", "Payment Request - Journal"),
]


def upgrade():
    # Idempotent: skips a code that already exists
    for code, name in _MODULES:
        op.execute(
            f"""
            INSERT INTO module_master (module_code, module_name, status)
            SELECT '{code}', '{name}', 'Active'
            WHERE NOT EXISTS (SELECT 1 FROM module_master WHERE module_code = '{code}')
            """
        )


def downgrade():
    # Rows are kept: approval_path rows may reference them (FK)
    pass
