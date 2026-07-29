"""Preserve normalized provider category and pending state."""
from alembic import op
import sqlalchemy as sa
revision='0003_transaction_source_metadata'; down_revision='0002_data_connections'; branch_labels=None; depends_on=None
def upgrade():
    op.add_column('transactions',sa.Column('source_category',sa.String(100),nullable=True))
    op.add_column('transactions',sa.Column('is_pending',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.alter_column('transactions','is_pending',server_default=None)
def downgrade():
    op.drop_column('transactions','is_pending');op.drop_column('transactions','source_category')
