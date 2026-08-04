"""Prevent anticipated expense rules from backfilling history."""
from alembic import op
import sqlalchemy as sa

revision='0025_anticipated_rule_start'
down_revision='0024_planner_effective_date'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('recurring_planner_expense_rules',sa.Column('effective_start_date',sa.Date(),nullable=True))
    op.execute("UPDATE recurring_planner_expense_rules SET effective_start_date = CAST(created_at AS DATE) WHERE effective_start_date IS NULL")

def downgrade():
    op.drop_column('recurring_planner_expense_rules','effective_start_date')
