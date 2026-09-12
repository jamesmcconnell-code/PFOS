"""Rename annual planner flag and add configurable proration duration."""
from alembic import op
import sqlalchemy as sa
revision = '0015_prorated_expenses'
down_revision = '0014_simple_mode'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.alter_column('is_annual', new_column_name='is_prorated')
        batch_op.add_column(sa.Column('proration_months', sa.Integer(), nullable=False, server_default='12'))
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.alter_column('proration_months', server_default=None)

def downgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('proration_months')
        batch_op.alter_column('is_prorated', new_column_name='is_annual')
