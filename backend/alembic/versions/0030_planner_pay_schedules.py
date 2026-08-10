"""Add household-member payroll schedule configuration."""
from alembic import op
import sqlalchemy as sa

revision='0030_planner_pay_schedules'
down_revision='0029_income_rule_end_date'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('planner_pay_schedules',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),
        sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('schedule_type',sa.String(20),nullable=False),
        sa.Column('biweekly_anchor_start_date',sa.Date(),nullable=True),
        sa.Column('paycheck_availability_policy',sa.String(20),nullable=False),
        sa.Column('is_active',sa.Boolean(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('household_id','owner_id',name='uq_planner_pay_schedule_household_owner'),
    )

def downgrade():
    op.drop_table('planner_pay_schedules')
