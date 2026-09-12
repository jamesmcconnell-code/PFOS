"""Add unlimited parent/child category hierarchy."""
from alembic import op
import sqlalchemy as sa
revision = '0017_category_hierarchy'
down_revision = '0016_account_balance_snapshots'
branch_labels = None
depends_on = None

def upgrade():
    # SQLite reflection cannot retain expression indexes during table rebuilds.
    op.drop_index('uq_categories_household_lower_name', table_name='categories')
    with op.batch_alter_table('categories') as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key('fk_categories_parent_id', 'categories', ['parent_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_categories_parent_id', 'categories', ['parent_id'])
    op.create_index('uq_categories_household_lower_name', 'categories', ['household_id', sa.text('lower(name)')], unique=True)

def downgrade():
    op.drop_index('uq_categories_household_lower_name', table_name='categories')
    op.drop_index('ix_categories_parent_id', table_name='categories')
    with op.batch_alter_table('categories') as batch_op:
        batch_op.drop_constraint('fk_categories_parent_id', type_='foreignkey')
        batch_op.drop_column('parent_id')
    op.create_index('uq_categories_household_lower_name', 'categories', ['household_id', sa.text('lower(name)')], unique=True)
