"""Allow multiple independently-authorized links for one institution."""
from alembic import op
revision = '0010_multi_plaid_links'
down_revision = '0009_goal_priorities'
branch_labels = None
depends_on = None
CONSTRAINT = 'data_connections_household_id_provider_name_key'

def upgrade():
    with op.batch_alter_table('data_connections') as batch_op:
        batch_op.drop_constraint(CONSTRAINT, type_='unique')

def downgrade():
    with op.batch_alter_table('data_connections') as batch_op:
        batch_op.create_unique_constraint(CONSTRAINT, ['household_id', 'provider', 'name'])
