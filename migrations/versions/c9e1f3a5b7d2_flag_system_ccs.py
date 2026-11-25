"""flag DSCR DSCA ROFI ROFE as system CCs

Revision ID: c9e1f3a5b7d2
Revises: b8d0f2a4e6c3
Create Date: 2026-11-25 20:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c9e1f3a5b7d2'
down_revision = 'b8d0f2a4e6c3'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE cc_codes SET is_system = TRUE
        WHERE cc_code IN ('DSCR', 'DSCA', 'ROFI', 'ROFE')
          AND is_system = FALSE
    """)


def downgrade():
    op.execute("""
        UPDATE cc_codes SET is_system = FALSE
        WHERE cc_code IN ('DSCR', 'DSCA', 'ROFI', 'ROFE')
    """)
