"""add is_system flag to cc_codes

Revision ID: b8d0f2a4e6c3
Revises: a7c9e1b3d5f2
Create Date: 2026-11-25 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8d0f2a4e6c3'
down_revision = 'a7c9e1b3d5f2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cc_codes', sa.Column(
        'is_system', sa.Boolean(), nullable=False, server_default=sa.false(),
    ))

    # Flag the 4 system-only CCs (discount & round-off split)
    op.execute("""
        UPDATE cc_codes SET is_system = TRUE
        WHERE cc_code IN ('DSCR', 'DSCA', 'ROFI', 'ROFE')
    """)


def downgrade():
    op.drop_column('cc_codes', 'is_system')
