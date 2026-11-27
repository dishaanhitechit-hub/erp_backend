"""MIS tasks: priority becomes Immediate / Scheduled; add handover_user_id

High / Critical → Immediate, Low / Medium (and anything else) → Scheduled.
Additive nullable handover_user_id column (who the finished work goes to).

Revision ID: 1f1d01e57404
Revises: 592455ed4e7e
Create Date: 2026-11-27 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '1f1d01e57404'
down_revision = '592455ed4e7e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.add_column(sa.Column('handover_user_id', sa.Integer(), nullable=True))
        b.create_index('ix_mis_tasks_handover_user_id', ['handover_user_id'], unique=False)
        b.create_foreign_key('fk_mis_tasks_handover_user_id', 'users', ['handover_user_id'], ['id'])
    op.execute("UPDATE mis_tasks SET priority = 'Immediate' WHERE priority IN ('High', 'Critical')")
    op.execute("UPDATE mis_tasks SET priority = 'Scheduled' WHERE priority NOT IN ('Immediate', 'Scheduled')")


def downgrade():
    op.execute("UPDATE mis_tasks SET priority = 'High' WHERE priority = 'Immediate'")
    op.execute("UPDATE mis_tasks SET priority = 'Medium' WHERE priority = 'Scheduled'")
    with op.batch_alter_table('mis_tasks', schema=None) as b:
        b.drop_constraint('fk_mis_tasks_handover_user_id', type_='foreignkey')
        b.drop_index('ix_mis_tasks_handover_user_id')
        b.drop_column('handover_user_id')
