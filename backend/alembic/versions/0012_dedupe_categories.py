"""Consolidate duplicate household categories and prevent future duplicates."""
from alembic import op

revision='0012_dedupe_categories'
down_revision='0011_cash_planner'
branch_labels=None
depends_on=None

def upgrade():
    # Preserve every transaction by moving it to the oldest matching category
    # before removing later duplicates (including duplicate Groceries records).
    op.execute("""
        WITH ranked AS (
          SELECT id, first_value(id) OVER (
            PARTITION BY household_id, lower(name) ORDER BY created_at, id
          ) AS retained_id
          FROM categories
        )
        UPDATE transactions AS txn
        SET category_id=ranked.retained_id
        FROM ranked
        WHERE txn.category_id=ranked.id AND ranked.id<>ranked.retained_id
    """)
    op.execute("""
        WITH ranked AS (
          SELECT id, row_number() OVER (
            PARTITION BY household_id, lower(name) ORDER BY created_at, id
          ) AS position
          FROM categories
        )
        DELETE FROM categories
        WHERE id IN (SELECT id FROM ranked WHERE position>1)
    """)
    op.execute('CREATE UNIQUE INDEX uq_categories_household_lower_name ON categories (household_id, lower(name))')

def downgrade():
    op.execute('DROP INDEX uq_categories_household_lower_name')
