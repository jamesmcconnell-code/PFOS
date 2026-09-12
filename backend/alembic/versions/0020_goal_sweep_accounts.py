"""Add the optional destination account for planner-only goal sweeps."""
from alembic import op
import sqlalchemy as sa
revision = '0020_goal_sweep_accounts'
down_revision = '0019_planner_carryovers'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('goals') as batch_op:
        batch_op.add_column(sa.Column('funding_account_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key('fk_goals_funding_account', 'accounts', ['funding_account_id'], ['id'], ondelete='SET NULL')

def downgrade():
    with op.batch_alter_table('goals') as batch_op:
        batch_op.drop_constraint('fk_goals_funding_account', type_='foreignkey')
        batch_op.drop_column('funding_account_id')
