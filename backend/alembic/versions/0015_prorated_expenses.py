"""Rename annual planner flag and add configurable proration duration."""
from alembic import op
import sqlalchemy as sa

revision='0015_prorated_expenses'
down_revision='0014_simple_mode'
branch_labels=None
depends_on=None

def upgrade():
    op.alter_column('transactions','is_annual',new_column_name='is_prorated')
    op.add_column('transactions',sa.Column('proration_months',sa.Integer(),nullable=False,server_default='12'))
    op.alter_column('transactions','proration_months',server_default=None)

def downgrade():
    op.drop_column('transactions','proration_months')
    op.alter_column('transactions','is_prorated',new_column_name='is_annual')
