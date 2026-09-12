"""Persist crypto USD valuations and increase quantity precision."""
from alembic import op
import sqlalchemy as sa
revision = '0008_crypto_usd_valuation'
down_revision = '0007_savings_engine'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.add_column(sa.Column('crypto_usd_value', sa.Numeric(18, 2), nullable=True))
        batch_op.add_column(sa.Column('crypto_price_updated_at', sa.DateTime(), nullable=True))
        batch_op.alter_column('balance', type_=sa.Numeric(24, 8), existing_type=sa.Numeric(14, 2))
    op.execute("UPDATE accounts SET asset_symbol=substr(name, 8) WHERE account_type='crypto' AND asset_symbol IS NULL AND name LIKE 'Gemini %'")

def downgrade():
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.alter_column('balance', type_=sa.Numeric(14, 2), existing_type=sa.Numeric(24, 8))
        batch_op.drop_column('crypto_price_updated_at')
        batch_op.drop_column('crypto_usd_value')
