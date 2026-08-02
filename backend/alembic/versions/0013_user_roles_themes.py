"""Add global user roles and theme preferences."""
from alembic import op
import sqlalchemy as sa

revision='0013_user_roles_themes'
down_revision='0012_dedupe_categories'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('role',sa.String(length=20),nullable=False,server_default='USER'))
    op.add_column('users',sa.Column('theme_preference',sa.String(length=30),nullable=False,server_default='system'))
    op.execute("UPDATE users SET role='ADMIN' WHERE id=(SELECT id FROM users ORDER BY created_at, id LIMIT 1)")
    op.alter_column('users','role',server_default=None)
    op.alter_column('users','theme_preference',server_default=None)

def downgrade():
    op.drop_column('users','theme_preference')
    op.drop_column('users','role')
