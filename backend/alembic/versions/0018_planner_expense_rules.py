"""Add explicit anticipated recurring planner expense rules."""
from alembic import op
import sqlalchemy as sa

revision='0018_planner_expense_rules'
down_revision='0017_category_hierarchy'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('recurring_planner_expense_rules',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),
        sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL'),nullable=True),
        sa.Column('source_transaction_id',sa.Uuid(),sa.ForeignKey('transactions.id',ondelete='SET NULL'),nullable=True),
        sa.Column('account_id',sa.Uuid(),sa.ForeignKey('accounts.id',ondelete='CASCADE'),nullable=False),
        sa.Column('category_id',sa.Uuid(),sa.ForeignKey('categories.id',ondelete='SET NULL'),nullable=True),
        sa.Column('display_name',sa.String(120),nullable=False),
        sa.Column('source_description',sa.String(255),nullable=True),
        sa.Column('monthly_projected_amount',sa.Numeric(14,2),nullable=False),
        sa.Column('expected_day_of_month',sa.Integer(),nullable=False,server_default='1'),
        sa.Column('cadence',sa.String(20),nullable=False,server_default='monthly'),
        sa.Column('is_active',sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column('proration_months',sa.Integer(),nullable=False,server_default='1'),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False),
    )
    op.create_index('ix_recurring_planner_expense_rules_household_active','recurring_planner_expense_rules',['household_id','is_active'])
    op.create_index('ix_recurring_planner_expense_rules_account','recurring_planner_expense_rules',['account_id'])

def downgrade():
    op.drop_index('ix_recurring_planner_expense_rules_account',table_name='recurring_planner_expense_rules')
    op.drop_index('ix_recurring_planner_expense_rules_household_active',table_name='recurring_planner_expense_rules')
    op.drop_table('recurring_planner_expense_rules')
