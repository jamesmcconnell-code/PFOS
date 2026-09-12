from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


def create_database_engine(url):
    """Build an application engine with SQLite integrity and lock handling."""
    sqlite = make_url(url).get_backend_name() == 'sqlite'
    options = {'connect_args': {'check_same_thread': False, 'timeout': 30}} if sqlite else {}
    engine = create_engine(url, pool_pre_ping=True, **options)
    if sqlite:
        @event.listens_for(engine, 'connect')
        def configure_sqlite(connection, _record):
            # Python's sqlite3 driver otherwise starts transactions only for DML.
            # Let SQLAlchemy begin transactions for DDL and reads as well.
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        @event.listens_for(engine, 'begin')
        def begin_sqlite(connection):
            connection.exec_driver_sql('BEGIN')
    return engine


engine = create_database_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
