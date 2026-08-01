"""Add persistent transaction planning flags."""
from alembic import op
import sqlalchemy as sa

revision='0011_cash_planner'
down_revision='0010_multi_plaid_links'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('transactions',sa.Column('is_refund',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('transactions',sa.Column('refund_included',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.add_column('transactions',sa.Column('is_expected',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('transactions',sa.Column('is_annual',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.alter_column('transactions','is_refund',server_default=None)
    op.alter_column('transactions','refund_included',server_default=None)
    op.alter_column('transactions','is_expected',server_default=None)
    op.alter_column('transactions','is_annual',server_default=None)

def downgrade():
    op.drop_column('transactions','is_annual')
    op.drop_column('transactions','is_expected')
    op.drop_column('transactions','refund_included')
    op.drop_column('transactions','is_refund')
