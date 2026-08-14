"""Add deterministic smart tagging audit fields and approval controls."""
from alembic import op
import sqlalchemy as sa

revision='0033_smart_tagging_engine'
down_revision='0032_smart_tagging_foundation'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('transactions',sa.Column('classification_rule_id',sa.Uuid(),sa.ForeignKey('transaction_classification_rules.id',ondelete='SET NULL'),nullable=True))
    op.add_column('transactions',sa.Column('classification_explanation',sa.Text(),nullable=True))
    op.add_column('transaction_classification_rules',sa.Column('name',sa.String(120),nullable=False,server_default='Classification rule'))
    op.add_column('transaction_classification_rules',sa.Column('planner_automation_approved',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('transaction_classification_suggestions',sa.Column('rule_id',sa.Uuid(),sa.ForeignKey('transaction_classification_rules.id',ondelete='SET NULL'),nullable=True))
    op.create_index('ix_transaction_classification_suggestions_rule_id','transaction_classification_suggestions',['rule_id'])

def downgrade():
    op.drop_index('ix_transaction_classification_suggestions_rule_id',table_name='transaction_classification_suggestions')
    op.drop_column('transaction_classification_suggestions','rule_id')
    op.drop_column('transaction_classification_rules','planner_automation_approved')
    op.drop_column('transaction_classification_rules','name')
    op.drop_column('transactions','classification_explanation')
    op.drop_column('transactions','classification_rule_id')
