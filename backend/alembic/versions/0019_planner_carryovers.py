"""Add persistent planner carryovers and signed adjustments."""
from alembic import op
import sqlalchemy as sa

revision='0019_planner_carryovers'
down_revision='0018_planner_expense_rules'
branch_labels=None
depends_on=None

def upgrade():
    for table in ('planner_starting_carryovers','planner_adjustments'):
        columns=[
            sa.Column('id',sa.Uuid(),primary_key=True),
            sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),
            sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL'),nullable=True),
            sa.Column('period_type',sa.String(20),nullable=False),
            sa.Column('effective_period_start',sa.Date(),nullable=False),
            sa.Column('amount',sa.Numeric(14,2),nullable=False),
            sa.Column('note',sa.Text(),nullable=True),
            sa.Column('created_at',sa.DateTime(),nullable=False),
            sa.Column('updated_at',sa.DateTime(),nullable=False),
        ]
        op.create_table(table,*columns)
        op.create_index(f'ix_{table}_scope_period',table,['household_id','owner_id','period_type','effective_period_start'])

def downgrade():
    for table in ('planner_adjustments','planner_starting_carryovers'):
        op.drop_index(f'ix_{table}_scope_period',table_name=table)
        op.drop_table(table)
