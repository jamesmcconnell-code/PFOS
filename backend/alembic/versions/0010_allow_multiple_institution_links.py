"""Allow multiple independently-authorized links for one institution."""
from alembic import op

revision='0010_multi_plaid_links'
down_revision='0009_goal_priorities'
branch_labels=None
depends_on=None

CONSTRAINT='data_connections_household_id_provider_name_key'

def upgrade():
    # A Plaid Item is an authorization, not an institution. Two household members
    # can each authorize Capital One, so provider/name cannot be unique.
    op.drop_constraint(CONSTRAINT, 'data_connections', type_='unique')

def downgrade():
    op.create_unique_constraint(CONSTRAINT, 'data_connections', ['household_id', 'provider', 'name'])
