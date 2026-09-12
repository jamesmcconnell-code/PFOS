"""Add connector credentials, sync auditing, and provider source provenance."""
from alembic import op
import sqlalchemy as sa
revision = '0002_data_connections'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('data_connections', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('household_id', sa.Uuid(), sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False), sa.Column('provider', sa.String(30), nullable=False), sa.Column('name', sa.String(120), nullable=False), sa.Column('status', sa.String(20), nullable=False), sa.Column('encrypted_credentials', sa.Text()), sa.Column('cursor', sa.Text()), sa.Column('last_synced_at', sa.DateTime()), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False), sa.UniqueConstraint('household_id', 'provider', 'name', name='data_connections_household_id_provider_name_key'))
    op.create_table('connection_syncs', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('connection_id', sa.Uuid(), sa.ForeignKey('data_connections.id', ondelete='CASCADE'), nullable=False), sa.Column('status', sa.String(20), nullable=False), sa.Column('imported_count', sa.Integer(), nullable=False), sa.Column('duplicate_count', sa.Integer(), nullable=False), sa.Column('error_message', sa.Text()), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False))
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.add_column(sa.Column('connection_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('external_id', sa.String(255), nullable=True))
        batch_op.create_foreign_key('fk_accounts_connection', 'data_connections', ['connection_id'], ['id'], ondelete='SET NULL')
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('connection_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('external_id', sa.String(255), nullable=True))
        batch_op.create_foreign_key('fk_transactions_connection', 'data_connections', ['connection_id'], ['id'], ondelete='SET NULL')
        batch_op.create_unique_constraint('uq_transaction_connection_external', ['connection_id', 'external_id'])

def downgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_constraint('uq_transaction_connection_external')
        batch_op.drop_constraint('fk_transactions_connection', type_='foreignkey')
        batch_op.drop_column('external_id')
        batch_op.drop_column('connection_id')
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.drop_constraint('fk_accounts_connection', type_='foreignkey')
        batch_op.drop_column('external_id')
        batch_op.drop_column('connection_id')
    op.drop_table('connection_syncs')
    op.drop_table('data_connections')
