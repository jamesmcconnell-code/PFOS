"""Add historical account balance snapshots for reporting."""
from alembic import op
import sqlalchemy as sa

revision='0016_account_balance_snapshots'
down_revision='0015_prorated_expenses'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('account_balance_snapshots',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),
        sa.Column('account_id',sa.Uuid(),sa.ForeignKey('accounts.id',ondelete='CASCADE'),nullable=False),
        sa.Column('snapshot_date',sa.Date(),nullable=False),
        sa.Column('balance',sa.Numeric(24,8),nullable=False),
        sa.Column('usd_value',sa.Numeric(18,2),nullable=True),
        sa.Column('source',sa.String(20),nullable=False,server_default='calculated'),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('account_id','snapshot_date',name='uq_account_balance_snapshot_date'),
    )
    op.create_index('ix_account_balance_snapshots_household_date','account_balance_snapshots',['household_id','snapshot_date'])

def downgrade():
    op.drop_index('ix_account_balance_snapshots_household_date',table_name='account_balance_snapshots')
    op.drop_table('account_balance_snapshots')
