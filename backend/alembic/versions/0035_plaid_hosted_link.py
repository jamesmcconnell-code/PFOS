"""Persist local Plaid authorization sessions across desktop restarts."""
from alembic import op
import sqlalchemy as sa
revision = '0035_plaid_hosted_link'
down_revision = '0034_smart_tagging_learning'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('plaid_link_sessions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('household_id', sa.Uuid(), sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('encrypted_state', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_plaid_link_sessions_user_id', 'plaid_link_sessions', ['user_id'])


def downgrade():
    op.drop_table('plaid_link_sessions')
