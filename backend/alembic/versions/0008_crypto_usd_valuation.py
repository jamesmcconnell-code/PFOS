"""Persist crypto USD valuations and increase quantity precision."""
from alembic import op
import sqlalchemy as sa

revision='0008_crypto_usd_valuation'
down_revision='0007_savings_engine'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('accounts',sa.Column('crypto_usd_value',sa.Numeric(18,2),nullable=True))
    op.add_column('accounts',sa.Column('crypto_price_updated_at',sa.DateTime(),nullable=True))
    op.alter_column('accounts','balance',type_=sa.Numeric(24,8),existing_type=sa.Numeric(14,2))
    op.execute("UPDATE accounts SET asset_symbol=regexp_replace(name, '^Gemini ', '') WHERE account_type='crypto' AND asset_symbol IS NULL AND name LIKE 'Gemini %'")
def downgrade():
    op.alter_column('accounts','balance',type_=sa.Numeric(14,2),existing_type=sa.Numeric(24,8));op.drop_column('accounts','crypto_price_updated_at');op.drop_column('accounts','crypto_usd_value')
