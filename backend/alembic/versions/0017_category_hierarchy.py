"""Add unlimited parent/child category hierarchy."""
from alembic import op
import sqlalchemy as sa

revision='0017_category_hierarchy'
down_revision='0016_account_balance_snapshots'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('categories',sa.Column('parent_id',sa.Uuid(),nullable=True))
    op.create_foreign_key('fk_categories_parent_id','categories','categories',['parent_id'],['id'],ondelete='SET NULL')
    op.create_index('ix_categories_parent_id','categories',['parent_id'])

def downgrade():
    op.drop_index('ix_categories_parent_id',table_name='categories')
    op.drop_constraint('fk_categories_parent_id','categories',type_='foreignkey')
    op.drop_column('categories','parent_id')
