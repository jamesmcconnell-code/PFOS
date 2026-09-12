"""Add explicit savings configuration and transfer markers."""
from alembic import op
import sqlalchemy as sa
revision = '0007_savings_engine'
down_revision = '0006_backfill_crypto_symbols'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.add_column(sa.Column('is_savings_direct_deposit', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('is_internal_transfer', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE transactions SET is_internal_transfer=true WHERE source_category IN ('TRANSFER_IN','TRANSFER_OUT')")
    op.create_table('savings_rules', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('household_id', sa.Uuid(), sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False), sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=True), sa.Column('category_id', sa.Uuid(), sa.ForeignKey('categories.id', ondelete='CASCADE'), nullable=True), sa.Column('tag_id', sa.Uuid(), sa.ForeignKey('tags.id', ondelete='CASCADE'), nullable=True), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False))
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.alter_column('is_savings_direct_deposit', server_default=None)
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.alter_column('is_internal_transfer', server_default=None)
    with op.batch_alter_table('savings_rules') as batch_op:
        batch_op.alter_column('is_active', server_default=None)

def downgrade():
    op.drop_table('savings_rules')
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('is_internal_transfer')
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.drop_column('is_savings_direct_deposit')
