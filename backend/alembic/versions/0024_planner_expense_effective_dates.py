"""Add planner-only effective dates for expense transactions."""
from alembic import op
import sqlalchemy as sa
revision = '0024_planner_effective_date'
down_revision = '0023_planner_income_allocations'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('planner_effective_date', sa.Date(), nullable=True))
    op.create_index('ix_transactions_planner_effective_date', 'transactions', ['planner_effective_date'])

def downgrade():
    op.drop_index('ix_transactions_planner_effective_date', table_name='transactions')
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('planner_effective_date')
