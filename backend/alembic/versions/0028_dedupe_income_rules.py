"""Remove the explicitly identified duplicate USAA payroll rule."""
from alembic import op

revision='0028_dedupe_income_rules'
down_revision='0027_backfill_income_rule_owner'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("DELETE FROM recurring_planner_income_rules WHERE id='f533c206-a297-4a7b-be38-fbc0c5f185af'")

def downgrade():
    pass
