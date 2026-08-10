"""Add scope-aware household settlement records."""
from alembic import op
import sqlalchemy as sa

revision='0031_household_settlements'
down_revision='0030_planner_pay_schedules'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('household_settlements',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),
        sa.Column('payer_transaction_id',sa.Uuid(),sa.ForeignKey('transactions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('recipient_transaction_id',sa.Uuid(),sa.ForeignKey('transactions.id',ondelete='SET NULL'),nullable=True),
        sa.Column('source_split_id',sa.Uuid(),sa.ForeignKey('transaction_splits.id',ondelete='SET NULL'),nullable=True),
        sa.Column('payer_user_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('recipient_user_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('settlement_amount',sa.Numeric(14,2),nullable=False),
        sa.Column('category_id',sa.Uuid(),sa.ForeignKey('categories.id',ondelete='SET NULL'),nullable=True),
        sa.Column('note',sa.Text(),nullable=True),
        sa.Column('settlement_group_id',sa.Uuid(),nullable=True),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('reversal_note',sa.Text(),nullable=True),
        sa.Column('reversed_at',sa.DateTime(),nullable=True),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False),
    )
    op.create_index('ix_household_settlements_household_id','household_settlements',['household_id'])
    op.create_index('ix_household_settlements_payer_transaction_id','household_settlements',['payer_transaction_id'])
    op.create_index('ix_household_settlements_recipient_transaction_id','household_settlements',['recipient_transaction_id'])
    op.create_index('ix_household_settlements_source_split_id','household_settlements',['source_split_id'])
    op.create_index('ix_household_settlements_payer_user_id','household_settlements',['payer_user_id'])
    op.create_index('ix_household_settlements_recipient_user_id','household_settlements',['recipient_user_id'])
    op.create_index('ix_household_settlements_settlement_group_id','household_settlements',['settlement_group_id'])
    op.create_index('ix_household_settlements_status','household_settlements',['status'])
    op.create_table('household_settlement_purchase_links',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('settlement_id',sa.Uuid(),sa.ForeignKey('household_settlements.id',ondelete='CASCADE'),nullable=False),
        sa.Column('original_transaction_id',sa.Uuid(),sa.ForeignKey('transactions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('original_split_id',sa.Uuid(),sa.ForeignKey('transaction_splits.id',ondelete='SET NULL'),nullable=True),
        sa.Column('allocated_amount',sa.Numeric(14,2),nullable=False),
        sa.Column('note',sa.Text(),nullable=True),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False),
    )
    op.create_index('ix_household_settlement_purchase_links_settlement_id','household_settlement_purchase_links',['settlement_id'])
    op.create_index('ix_household_settlement_purchase_links_original_transaction_id','household_settlement_purchase_links',['original_transaction_id'])
    op.create_index('ix_household_settlement_purchase_links_original_split_id','household_settlement_purchase_links',['original_split_id'])

def downgrade():
    op.drop_table('household_settlement_purchase_links')
    op.drop_table('household_settlements')
