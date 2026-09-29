"""Allow a real debit to be excluded only from Available Cash."""
from alembic import op
import sqlalchemy as sa

revision = '0036_available_cash_exclusions'
down_revision = '0035_plaid_hosted_link'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('exclude_from_available_cash', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('transactions', 'exclude_from_available_cash')
