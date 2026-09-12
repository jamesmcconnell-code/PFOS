"""Preserve normalized provider category and pending state."""
from alembic import op
import sqlalchemy as sa
revision = '0003_transaction_source_metadata'
down_revision = '0002_data_connections'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('source_category', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('is_pending', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.alter_column('is_pending', server_default=None)

def downgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('is_pending')
        batch_op.drop_column('source_category')
