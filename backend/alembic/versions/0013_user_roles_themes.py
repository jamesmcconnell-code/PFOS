"""Add global user roles and theme preferences."""
from alembic import op
import sqlalchemy as sa
revision = '0013_user_roles_themes'
down_revision = '0012_dedupe_categories'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=20), nullable=False, server_default='USER'))
        batch_op.add_column(sa.Column('theme_preference', sa.String(length=30), nullable=False, server_default='system'))
    op.execute("UPDATE users SET role='ADMIN' WHERE id=(SELECT id FROM users ORDER BY created_at, id LIMIT 1)")
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('role', server_default=None)
        batch_op.alter_column('theme_preference', server_default=None)

def downgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('theme_preference')
        batch_op.drop_column('role')
