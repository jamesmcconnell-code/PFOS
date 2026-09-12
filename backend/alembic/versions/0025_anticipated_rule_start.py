"""Prevent anticipated expense rules from backfilling history."""
from alembic import op
import sqlalchemy as sa
revision = '0025_anticipated_rule_start'
down_revision = '0024_planner_effective_date'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('recurring_planner_expense_rules') as batch_op:
        batch_op.add_column(sa.Column('effective_start_date', sa.Date(), nullable=True))
    date_expression = 'date(created_at)' if op.get_bind().dialect.name == 'sqlite' else 'CAST(created_at AS DATE)'
    op.execute(f'UPDATE recurring_planner_expense_rules SET effective_start_date = {date_expression} WHERE effective_start_date IS NULL')

def downgrade():
    with op.batch_alter_table('recurring_planner_expense_rules') as batch_op:
        batch_op.drop_column('effective_start_date')
