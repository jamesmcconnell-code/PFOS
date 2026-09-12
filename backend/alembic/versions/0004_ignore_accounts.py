"""Prevent user-deleted synced accounts from returning on a future sync."""
from alembic import op
import sqlalchemy as sa
revision = '0004_ignore_accounts'
down_revision = '0003_transaction_source_metadata'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('data_connections') as batch_op:
        batch_op.add_column(sa.Column('ignored_account_ids', sa.Text(), nullable=False, server_default='[]'))
    with op.batch_alter_table('data_connections') as batch_op:
        batch_op.alter_column('ignored_account_ids', server_default=None)

def downgrade():
    with op.batch_alter_table('data_connections') as batch_op:
        batch_op.drop_column('ignored_account_ids')
