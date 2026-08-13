"""Add privacy-first smart tagging foundation tables."""
from alembic import op
import sqlalchemy as sa

revision='0032_smart_tagging_foundation'
down_revision='0031_household_settlements'
branch_labels=None
depends_on=None

def audit_columns():
    return [sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False)]

def upgrade():
    op.create_table('merchant_identities',
        sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),
        sa.Column('normalized_merchant_key',sa.String(255),nullable=False),sa.Column('display_name',sa.String(255),nullable=False),sa.Column('source_metadata',sa.Text(),nullable=True),
        *audit_columns(),sa.UniqueConstraint('household_id','normalized_merchant_key',name='uq_merchant_identity_household_key'))
    op.create_index('ix_merchant_identities_household_id','merchant_identities',['household_id'])
    op.create_table('transaction_classification_rules',
        sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),
        sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL'),nullable=True),sa.Column('account_id',sa.Uuid(),sa.ForeignKey('accounts.id',ondelete='CASCADE'),nullable=True),
        sa.Column('normalized_merchant_key',sa.String(255),nullable=True),sa.Column('description_pattern',sa.String(255),nullable=True),sa.Column('direction',sa.String(10),nullable=False),sa.Column('financial_role',sa.String(20),nullable=True),
        sa.Column('category_id',sa.Uuid(),sa.ForeignKey('categories.id',ondelete='SET NULL'),nullable=True),sa.Column('classified_owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL'),nullable=True),
        sa.Column('essential',sa.Boolean(),nullable=True),sa.Column('internal_transfer',sa.Boolean(),nullable=True),sa.Column('refund_credit',sa.Boolean(),nullable=True),sa.Column('loan_reimbursement',sa.Boolean(),nullable=True),sa.Column('expected',sa.Boolean(),nullable=True),sa.Column('prorated',sa.Boolean(),nullable=True),sa.Column('proration_months',sa.Integer(),nullable=True),
        sa.Column('priority',sa.Integer(),nullable=False),sa.Column('is_active',sa.Boolean(),nullable=False),sa.Column('source_type',sa.String(20),nullable=False),*audit_columns())
    for name,column in [('household_id','household_id'),('owner_id','owner_id'),('account_id','account_id'),('normalized_merchant_key','normalized_merchant_key'),('priority','priority'),('is_active','is_active')]: op.create_index(f'ix_transaction_classification_rules_{name}','transaction_classification_rules',[column])
    op.create_table('transaction_classification_rule_tags',sa.Column('rule_id',sa.Uuid(),sa.ForeignKey('transaction_classification_rules.id',ondelete='CASCADE'),primary_key=True),sa.Column('tag_id',sa.Uuid(),sa.ForeignKey('tags.id',ondelete='CASCADE'),primary_key=True))
    op.create_table('transaction_classification_suggestions',
        sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('household_id',sa.Uuid(),sa.ForeignKey('households.id',ondelete='CASCADE'),nullable=False),sa.Column('transaction_id',sa.Uuid(),sa.ForeignKey('transactions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('category_id',sa.Uuid(),sa.ForeignKey('categories.id',ondelete='SET NULL'),nullable=True),sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL'),nullable=True),
        sa.Column('essential',sa.Boolean(),nullable=True),sa.Column('internal_transfer',sa.Boolean(),nullable=True),sa.Column('refund_credit',sa.Boolean(),nullable=True),sa.Column('loan_reimbursement',sa.Boolean(),nullable=True),sa.Column('expected',sa.Boolean(),nullable=True),sa.Column('prorated',sa.Boolean(),nullable=True),sa.Column('proration_months',sa.Integer(),nullable=True),
        sa.Column('confidence_score',sa.Numeric(5,4),nullable=False),sa.Column('explanation',sa.Text(),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('safe_for_auto_apply',sa.Boolean(),nullable=False),*audit_columns())
    for name,column in [('household_id','household_id'),('transaction_id','transaction_id'),('status','status')]: op.create_index(f'ix_transaction_classification_suggestions_{name}','transaction_classification_suggestions',[column])
    op.create_table('transaction_classification_suggestion_tags',sa.Column('suggestion_id',sa.Uuid(),sa.ForeignKey('transaction_classification_suggestions.id',ondelete='CASCADE'),primary_key=True),sa.Column('tag_id',sa.Uuid(),sa.ForeignKey('tags.id',ondelete='CASCADE'),primary_key=True))

def downgrade():
    op.drop_table('transaction_classification_suggestion_tags')
    op.drop_table('transaction_classification_suggestions')
    op.drop_table('transaction_classification_rule_tags')
    op.drop_table('transaction_classification_rules')
    op.drop_table('merchant_identities')
