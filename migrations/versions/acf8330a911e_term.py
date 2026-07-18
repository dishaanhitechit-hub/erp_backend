"""term

Revision ID: acf8330a911e
Revises: fc2f4f554911
Create Date: 2026-07-18 15:54:55.666115

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'acf8330a911e'
down_revision = 'fc2f4f554911'
branch_labels = None
depends_on = None


def _get_fk_name(conn, table, ref_table):
    """Return the name of the FK constraint on `table` referencing `ref_table`."""
    result = conn.execute(sa.text("""
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.referential_constraints rc
            ON tc.constraint_name = rc.constraint_name
        JOIN information_schema.constraint_column_usage ccu
            ON rc.unique_constraint_name = ccu.constraint_name
        WHERE tc.table_name = :table
          AND ccu.table_name = :ref_table
          AND tc.constraint_type = 'FOREIGN KEY'
        LIMIT 1
    """), {"table": table, "ref_table": ref_table})
    row = result.fetchone()
    return row[0] if row else None


def upgrade():
    conn = op.get_bind()

    for table in ('order_terms_conditions', 'pw_order_terms_conditions'):
        # add custom_groups if not already present
        cols = [r[0] for r in conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
        ), {"t": table}).fetchall()]

        if 'custom_groups' not in cols:
            op.add_column(table, sa.Column('custom_groups', sa.Text(), nullable=True))

        # drop old FK to term_conditions
        fk = _get_fk_name(conn, table, 'term_conditions')
        if fk:
            op.drop_constraint(fk, table, type_='foreignkey')

        # create new FK to terms
        new_fk = _get_fk_name(conn, table, 'terms')
        if not new_fk:
            op.create_foreign_key(None, table, 'terms', ['term_id'], ['term_id'])

        # drop custom_description if still present
        if 'custom_description' in cols:
            op.drop_column(table, 'custom_description')


def downgrade():
    conn = op.get_bind()

    for table in ('order_terms_conditions', 'pw_order_terms_conditions'):
        cols = [r[0] for r in conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
        ), {"t": table}).fetchall()]

        if 'custom_description' not in cols:
            op.add_column(table, sa.Column('custom_description', sa.Text(), nullable=True))

        fk = _get_fk_name(conn, table, 'terms')
        if fk:
            op.drop_constraint(fk, table, type_='foreignkey')

        op.create_foreign_key(None, table, 'term_conditions', ['term_id'], ['id'])

        if 'custom_groups' in cols:
            op.drop_column(table, 'custom_groups')
