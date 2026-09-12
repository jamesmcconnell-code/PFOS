"""Scope legacy paycheck rules to their individual source accounts."""
from alembic import op

revision='0027_backfill_income_rule_owner'
down_revision='0026_recurring_income_rules'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("UPDATE recurring_planner_income_rules AS r SET owner_id=a.owner_id FROM accounts a WHERE r.account_id=a.id AND r.owner_id IS NULL AND a.ownership='individual' AND a.owner_id IS NOT NULL")

def downgrade():
    pass
