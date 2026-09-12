"""Add household account classifications, ownership, and crypto asset symbol."""
from alembic import op
import sqlalchemy as sa
revision = '0005_account_roles'
down_revision = '0004_ignore_accounts'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key('fk_accounts_owner', 'users', ['owner_id'], ['id'], ondelete='SET NULL')
        batch_op.add_column(sa.Column('ownership', sa.String(20), nullable=False, server_default='joint'))
        batch_op.add_column(sa.Column('account_type', sa.String(20), nullable=False, server_default='spending'))
        batch_op.add_column(sa.Column('asset_symbol', sa.String(20), nullable=True))
    op.execute("UPDATE accounts SET account_type=CASE WHEN type='credit_card' THEN 'debt' WHEN type='crypto' THEN 'crypto' WHEN type='savings' THEN 'income' WHEN type='brokerage' THEN 'brokerage' ELSE 'spending' END")
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.alter_column('ownership', server_default=None)
        batch_op.alter_column('account_type', server_default=None)

def downgrade():
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.drop_constraint('fk_accounts_owner', type_='foreignkey')
        batch_op.drop_column('asset_symbol')
        batch_op.drop_column('account_type')
        batch_op.drop_column('ownership')
        batch_op.drop_column('owner_id')
