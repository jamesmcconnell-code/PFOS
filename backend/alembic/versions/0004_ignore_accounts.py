"""Prevent user-deleted synced accounts from returning on a future sync."""
from alembic import op
import sqlalchemy as sa
revision='0004_ignore_accounts'; down_revision='0003_transaction_source_metadata'; branch_labels=None; depends_on=None
def upgrade():
    op.add_column('data_connections',sa.Column('ignored_account_ids',sa.Text(),nullable=False,server_default='[]'))
    op.alter_column('data_connections','ignored_account_ids',server_default=None)
def downgrade(): op.drop_column('data_connections','ignored_account_ids')
