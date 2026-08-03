"""Add allocation-specific tags and refund treatment."""
from alembic import op
import sqlalchemy as sa

revision='0022_split_tags_and_refunds'
down_revision='0021_transaction_split_metadata'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('transaction_splits',sa.Column('is_refund',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('transaction_splits',sa.Column('refund_included',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('transaction_split_tags',sa.Column('split_id',sa.Uuid(),sa.ForeignKey('transaction_splits.id',ondelete='CASCADE'),primary_key=True),sa.Column('tag_id',sa.Uuid(),sa.ForeignKey('tags.id',ondelete='CASCADE'),primary_key=True))

def downgrade():
    op.drop_table('transaction_split_tags')
    op.drop_column('transaction_splits','refund_included')
    op.drop_column('transaction_splits','is_refund')
