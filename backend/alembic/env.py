from alembic import context
from sqlalchemy import event
from app.database import Base, create_database_engine
from app import models
from app.config import settings

config = context.config
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = create_database_engine(settings.database_url)
    if connectable.dialect.name == 'sqlite':
        # Batch migrations rebuild referenced tables. Disable enforcement only
        # on this private migration connection, then validate before committing.
        @event.listens_for(connectable, 'connect')
        def migration_foreign_keys(connection, _record):
            connection.execute('PRAGMA foreign_keys=OFF')
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata,
                              render_as_batch=connection.dialect.name == 'sqlite',
                              transactional_ddl=True)
            with context.begin_transaction():
                context.run_migrations()
                if connection.dialect.name == 'sqlite':
                    if connection.exec_driver_sql('PRAGMA foreign_key_check').first():
                        raise RuntimeError('Migration would leave invalid foreign keys; changes rolled back')
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
