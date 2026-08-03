"""Add planner-only paycheck availability allocations."""
from alembic import op
import sqlalchemy as sa

revision='0023_planner_income_allocations'
down_revision='0022_split_tags_and_refunds'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('planner_income_allocations',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL'),nullable=True),sa.Column('source_transaction_id',sa.Uuid(),sa.ForeignKey('transactions.id',ondelete='CASCADE'),nullable=False),sa.Column('period_type',sa.String(20),nullable=False),sa.Column('effective_period_start',sa.Date(),nullable=False),sa.Column('amount',sa.Numeric(14,2),nullable=False),sa.Column('note',sa.Text(),nullable=True),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_index('ix_planner_income_allocations_scope_period','planner_income_allocations',['household_id','owner_id','period_type','effective_period_start'])
    op.create_index('ix_planner_income_allocations_source','planner_income_allocations',['source_transaction_id'])

def downgrade():
    op.drop_index('ix_planner_income_allocations_source',table_name='planner_income_allocations')
    op.drop_index('ix_planner_income_allocations_scope_period',table_name='planner_income_allocations')
    op.drop_table('planner_income_allocations')
