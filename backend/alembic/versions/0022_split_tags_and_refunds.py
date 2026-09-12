"""Add allocation-specific tags and refund treatment."""
from alembic import op
import sqlalchemy as sa
revision = '0022_split_tags_and_refunds'
down_revision = '0021_transaction_split_metadata'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('transaction_splits') as batch_op:
        batch_op.add_column(sa.Column('is_refund', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('refund_included', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table('transaction_split_tags', sa.Column('split_id', sa.Uuid(), sa.ForeignKey('transaction_splits.id', ondelete='CASCADE'), primary_key=True), sa.Column('tag_id', sa.Uuid(), sa.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True))

def downgrade():
    op.drop_table('transaction_split_tags')
    with op.batch_alter_table('transaction_splits') as batch_op:
        batch_op.drop_column('refund_included')
        batch_op.drop_column('is_refund')
