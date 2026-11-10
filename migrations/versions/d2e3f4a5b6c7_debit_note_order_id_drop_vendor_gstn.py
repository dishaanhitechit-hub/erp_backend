"""debit_note: add order_id FK, drop vendor_gstn

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-10 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "debit_note_master",
        sa.Column("order_id", sa.Integer, sa.ForeignKey("order_master.id"), nullable=True),
    )
    op.drop_column("debit_note_master", "vendor_gstn")


def downgrade():
    op.drop_column("debit_note_master", "order_id")
    op.add_column(
        "debit_note_master",
        sa.Column("vendor_gstn", sa.String(50), nullable=True),
    )
