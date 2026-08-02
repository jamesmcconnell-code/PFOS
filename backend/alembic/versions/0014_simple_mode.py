"""Add per-user whimsical simple mode preference."""
from alembic import op
import sqlalchemy as sa

revision='0014_simple_mode'
down_revision='0013_user_roles_themes'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('simple_mode_enabled',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.alter_column('users','simple_mode_enabled',server_default=None)

def downgrade():
    op.drop_column('users','simple_mode_enabled')
