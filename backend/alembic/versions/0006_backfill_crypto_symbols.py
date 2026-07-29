"""Backfill asset symbols for existing Coinbase wallet accounts."""
from alembic import op

revision = '0006_backfill_crypto_symbols'
down_revision = '0005_account_roles'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE accounts
        SET asset_symbol = regexp_replace(name, ' Wallet$', '')
        WHERE account_type = 'crypto'
          AND asset_symbol IS NULL
          AND name LIKE '% Wallet'
    """)
    op.execute("""
        UPDATE accounts
        SET asset_symbol = 'USD'
        WHERE account_type = 'crypto'
          AND asset_symbol IS NULL
          AND name = 'Cash (USD)'
    """)


def downgrade():
    pass
