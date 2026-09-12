"""Add persistent transaction planning flags."""
from alembic import op
import sqlalchemy as sa
revision = '0011_cash_planner'
down_revision = '0010_multi_plaid_links'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('is_refund', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('refund_included', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('is_expected', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('is_annual', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.alter_column('is_refund', server_default=None)
        batch_op.alter_column('refund_included', server_default=None)
        batch_op.alter_column('is_expected', server_default=None)
        batch_op.alter_column('is_annual', server_default=None)

def downgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('is_annual')
        batch_op.drop_column('is_expected')
        batch_op.drop_column('refund_included')
        batch_op.drop_column('is_refund')
