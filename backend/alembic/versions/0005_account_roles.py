"""Add household account classifications, ownership, and crypto asset symbol."""
from alembic import op
import sqlalchemy as sa
revision='0005_account_roles'; down_revision='0004_ignore_accounts'; branch_labels=None; depends_on=None
def upgrade():
    op.add_column('accounts',sa.Column('owner_id',sa.Uuid(),nullable=True));op.create_foreign_key('fk_accounts_owner','accounts','users',['owner_id'],['id'],ondelete='SET NULL')
    op.add_column('accounts',sa.Column('ownership',sa.String(20),nullable=False,server_default='joint'))
    op.add_column('accounts',sa.Column('account_type',sa.String(20),nullable=False,server_default='spending'))
    op.add_column('accounts',sa.Column('asset_symbol',sa.String(20),nullable=True))
    op.execute("UPDATE accounts SET account_type=CASE WHEN type='credit_card' THEN 'debt' WHEN type='crypto' THEN 'crypto' WHEN type='savings' THEN 'income' WHEN type='brokerage' THEN 'brokerage' ELSE 'spending' END")
    op.alter_column('accounts','ownership',server_default=None);op.alter_column('accounts','account_type',server_default=None)
def downgrade():
    op.drop_constraint('fk_accounts_owner','accounts',type_='foreignkey');op.drop_column('accounts','asset_symbol');op.drop_column('accounts','account_type');op.drop_column('accounts','ownership');op.drop_column('accounts','owner_id')
