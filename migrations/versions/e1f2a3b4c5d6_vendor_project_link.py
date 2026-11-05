"""vendor project link table

Revision ID: e1f2a3b4c5d6
Revises: da3d6c70cc55
Create Date: 2026-11-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d6'
down_revision = 'da3d6c70cc55'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vendor_project',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vendor_id', sa.Integer(), sa.ForeignKey('vendors.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('vendor_id', 'project_id', name='uq_vendor_project'),
    )
    op.create_index('ix_vendor_project_vendor_id', 'vendor_project', ['vendor_id'])
    op.create_index('ix_vendor_project_project_id', 'vendor_project', ['project_id'])


def downgrade():
    op.drop_index('ix_vendor_project_project_id', table_name='vendor_project')
    op.drop_index('ix_vendor_project_vendor_id', table_name='vendor_project')
    op.drop_table('vendor_project')
