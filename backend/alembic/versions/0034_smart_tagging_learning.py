"""Add local smart-tagging learning evidence and decision audit trail."""
from alembic import op
import sqlalchemy as sa

revision='0034_smart_tagging_learning'
down_revision='0033_smart_tagging_engine'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('transaction_classification_suggestions',sa.Column('proposal_data',sa.Text(),nullable=True))
    op.add_column('transaction_classification_suggestions',sa.Column('evidence_data',sa.Text(),nullable=True))
    op.add_column('transaction_classification_suggestions',sa.Column('recurring',sa.Boolean(),nullable=True))
    op.add_column('transaction_classification_suggestions',sa.Column('source_type',sa.String(20),nullable=False,server_default='rule'))
    op.create_table('transaction_classification_suggestion_decisions',
        sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('suggestion_id',sa.Uuid(),sa.ForeignKey('transaction_classification_suggestions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('field_name',sa.String(40),nullable=False),sa.Column('decision',sa.String(20),nullable=False),sa.Column('value_data',sa.Text(),nullable=True),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False),sa.UniqueConstraint('suggestion_id','field_name',name='uq_suggestion_decision_field'))
    # PostgreSQL identifiers are capped at 63 characters.
    op.create_index('ix_st_suggestion_decision_suggestion','transaction_classification_suggestion_decisions',['suggestion_id'])

def downgrade():
    op.drop_table('transaction_classification_suggestion_decisions')
    op.drop_column('transaction_classification_suggestions','source_type')
    op.drop_column('transaction_classification_suggestions','recurring')
    op.drop_column('transaction_classification_suggestions','evidence_data')
    op.drop_column('transaction_classification_suggestions','proposal_data')
