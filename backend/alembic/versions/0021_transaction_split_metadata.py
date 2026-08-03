"""Add category and ownership metadata to transaction allocations."""
from alembic import op
import sqlalchemy as sa

revision='0021_transaction_split_metadata'
down_revision='0020_goal_sweep_accounts'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('transaction_splits',sa.Column('owner_id',sa.Uuid(),nullable=True))
    op.add_column('transaction_splits',sa.Column('ownership',sa.String(20),nullable=False,server_default='joint'))
    op.add_column('transaction_splits',sa.Column('category_id',sa.Uuid(),nullable=True))
    op.create_foreign_key('fk_transaction_splits_owner','transaction_splits','users',['owner_id'],['id'],ondelete='SET NULL')
    op.create_foreign_key('fk_transaction_splits_category','transaction_splits','categories',['category_id'],['id'],ondelete='SET NULL')

def downgrade():
    op.drop_constraint('fk_transaction_splits_category','transaction_splits',type_='foreignkey')
    op.drop_constraint('fk_transaction_splits_owner','transaction_splits',type_='foreignkey')
    op.drop_column('transaction_splits','category_id')
    op.drop_column('transaction_splits','ownership')
    op.drop_column('transaction_splits','owner_id')
