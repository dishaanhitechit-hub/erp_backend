"""claim bill bill number added

Revision ID: fa2e352a0154
Revises: dce9baa1826f
Create Date: 2026-10-30 20:41:15.064221

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fa2e352a0154'
down_revision = 'dce9baa1826f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('billing_master', schema=None) as batch_op:
        batch_op.add_column(sa.Column('note', sa.String(length=500), nullable=True))
        batch_op.drop_column('title')


def downgrade():
    with op.batch_alter_table('billing_master', schema=None) as batch_op:
        batch_op.add_column(sa.Column('title', sa.VARCHAR(length=500), autoincrement=False, nullable=True))
        batch_op.drop_column('note')
