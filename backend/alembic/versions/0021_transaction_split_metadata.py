"""Add category and ownership metadata to transaction allocations."""
from alembic import op
import sqlalchemy as sa
revision = '0021_transaction_split_metadata'
down_revision = '0020_goal_sweep_accounts'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('transaction_splits') as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('ownership', sa.String(20), nullable=False, server_default='joint'))
        batch_op.add_column(sa.Column('category_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key('fk_transaction_splits_owner', 'users', ['owner_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_transaction_splits_category', 'categories', ['category_id'], ['id'], ondelete='SET NULL')

def downgrade():
    with op.batch_alter_table('transaction_splits') as batch_op:
        batch_op.drop_constraint('fk_transaction_splits_category', type_='foreignkey')
        batch_op.drop_constraint('fk_transaction_splits_owner', type_='foreignkey')
        batch_op.drop_column('category_id')
        batch_op.drop_column('ownership')
        batch_op.drop_column('owner_id')
