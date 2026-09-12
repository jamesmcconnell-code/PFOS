"""Add deterministic smart tagging audit fields and approval controls."""
from alembic import op
import sqlalchemy as sa
revision = '0033_smart_tagging_engine'
down_revision = '0032_smart_tagging_foundation'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('classification_rule_id', sa.Uuid(), sa.ForeignKey('transaction_classification_rules.id', name='fk_transactions_classification_rule', ondelete='SET NULL'), nullable=True))
        batch_op.add_column(sa.Column('classification_explanation', sa.Text(), nullable=True))
    with op.batch_alter_table('transaction_classification_rules') as batch_op:
        batch_op.add_column(sa.Column('name', sa.String(120), nullable=False, server_default='Classification rule'))
        batch_op.add_column(sa.Column('planner_automation_approved', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('transaction_classification_suggestions') as batch_op:
        batch_op.add_column(sa.Column('rule_id', sa.Uuid(), sa.ForeignKey('transaction_classification_rules.id', name='fk_suggestions_classification_rule', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_transaction_classification_suggestions_rule_id', 'transaction_classification_suggestions', ['rule_id'])

def downgrade():
    op.drop_index('ix_transaction_classification_suggestions_rule_id', table_name='transaction_classification_suggestions')
    with op.batch_alter_table('transaction_classification_suggestions') as batch_op:
        batch_op.drop_column('rule_id')
    with op.batch_alter_table('transaction_classification_rules') as batch_op:
        batch_op.drop_column('planner_automation_approved')
        batch_op.drop_column('name')
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('classification_explanation')
        batch_op.drop_column('classification_rule_id')
