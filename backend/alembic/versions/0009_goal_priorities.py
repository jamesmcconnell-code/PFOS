"""Add shared goal ranking, goal progress, and checking ceiling configuration."""
from alembic import op
import sqlalchemy as sa
revision = '0009_goal_priorities'
down_revision = '0008_crypto_usd_valuation'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('households') as batch_op:
        batch_op.add_column(sa.Column('checking_account_ceiling', sa.Numeric(14, 2), nullable=False, server_default='0'))
    with op.batch_alter_table('goals') as batch_op:
        batch_op.add_column(sa.Column('current_amount', sa.Numeric(14, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('priority_order', sa.Integer(), nullable=False, server_default='0'))
    op.execute('UPDATE goals SET current_amount=COALESCE((SELECT SUM(amount) FROM goal_contributions WHERE goal_contributions.goal_id=goals.id),0)')
    op.execute('UPDATE goals SET priority_order=ranked.position FROM (SELECT id, row_number() OVER (PARTITION BY household_id ORDER BY created_at, id)-1 AS position FROM goals) ranked WHERE goals.id=ranked.id')
    with op.batch_alter_table('households') as batch_op:
        batch_op.alter_column('checking_account_ceiling', server_default=None)
    with op.batch_alter_table('goals') as batch_op:
        batch_op.alter_column('current_amount', server_default=None)
        batch_op.alter_column('priority_order', server_default=None)

def downgrade():
    with op.batch_alter_table('goals') as batch_op:
        batch_op.drop_column('priority_order')
        batch_op.drop_column('current_amount')
    with op.batch_alter_table('households') as batch_op:
        batch_op.drop_column('checking_account_ceiling')
