"""MIS Boards: per-person committed / done points on sprint snapshots (performance score)

Additive nullable JSON column on mis_sprint_snapshots.

Revision ID: 592455ed4e7e
Revises: 0b21b0d4b94c
Create Date: 2026-11-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '592455ed4e7e'
down_revision = '0b21b0d4b94c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mis_sprint_snapshots', schema=None) as b:
        b.add_column(sa.Column('people', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('mis_sprint_snapshots', schema=None) as b:
        b.drop_column('people')
