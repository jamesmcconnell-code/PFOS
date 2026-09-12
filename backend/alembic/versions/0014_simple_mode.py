"""Add per-user whimsical simple mode preference."""
from alembic import op
import sqlalchemy as sa
revision = '0014_simple_mode'
down_revision = '0013_user_roles_themes'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('simple_mode_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('simple_mode_enabled', server_default=None)

def downgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('simple_mode_enabled')
