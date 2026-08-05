"""Preserve historical paycheck forecasts when a recurring rule changes."""
from alembic import op
import sqlalchemy as sa

revision='0029_income_rule_end_date'
down_revision='0028_dedupe_income_rules'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('recurring_planner_income_rules',sa.Column('effective_end_date',sa.Date(),nullable=True))

def downgrade():
    op.drop_column('recurring_planner_income_rules','effective_end_date')
