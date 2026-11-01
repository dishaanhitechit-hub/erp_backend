"""comm conversation member invite status

Revision ID: a7c3e91d2b40
Revises: 48944c9768ae
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c3e91d2b40"
down_revision = "48944c9768ae"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("comm_conversation_members") as b:
        b.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="active"))
        b.add_column(sa.Column("invited_by", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("comm_conversation_members") as b:
        b.drop_column("invited_by")
        b.drop_column("status")
