"""Add the optional destination account for planner-only goal sweeps."""
from alembic import op
import sqlalchemy as sa

revision='0020_goal_sweep_accounts'
down_revision='0019_planner_carryovers'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('goals',sa.Column('funding_account_id',sa.Uuid(),nullable=True))
    op.create_foreign_key('fk_goals_funding_account','goals','accounts',['funding_account_id'],['id'],ondelete='SET NULL')

def downgrade():
    op.drop_constraint('fk_goals_funding_account','goals',type_='foreignkey')
    op.drop_column('goals','funding_account_id')
