"""Exercise actual migrations and on-disk storage, not metadata.create_all()."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, create_database_engine, get_db
from app.main import app
from app.models import Account, Category, Household, Transaction, TransactionTag, Tag


@pytest.fixture
def storage(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "household.db"}'
    monkeypatch.setattr(settings, 'database_url', url)
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'alembic'))
    return url, config


def test_fresh_migration_matches_models_and_is_repeatable(storage):
    url, config = storage
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
    engine = create_database_engine(url)
    try:
        with engine.connect() as connection:
            schema = inspect(connection)
            assert set(schema.get_table_names()) == set(Base.metadata.tables) | {'alembic_version'}
            for name, table in Base.metadata.tables.items():
                columns = {column['name']: column for column in schema.get_columns(name)}
                assert set(columns) == set(table.columns.keys()), name
                for column in table.columns:
                    assert columns[column.name]['nullable'] == column.nullable, (name, column.name)
                actual_fks = {(tuple(fk['constrained_columns']), fk['referred_table'], tuple(fk['referred_columns']), fk['options'].get('ondelete')) for fk in schema.get_foreign_keys(name)}
                expected_fks = {(tuple(fk.column_keys), fk.referred_table.name, tuple(element.column.name for element in fk.elements), fk.ondelete) for fk in table.foreign_key_constraints}
                assert actual_fks == expected_fks, name
            assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == ScriptDirectory.from_config(config).get_current_head()
            assert connection.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
            assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()
    finally:
        engine.dispose()


def test_upgrade_preserves_existing_rows_and_backfills_dates(storage):
    url, config = storage
    command.upgrade(config, '0001_initial')
    engine = create_database_engine(url)
    home_id, account_id, category_id, duplicate_id, transaction_id = [uuid4() for _ in range(5)]
    audit = {'created_at': datetime(2026, 7, 1, 12), 'updated_at': datetime(2026, 7, 1, 12)}
    def insert(table, **values):
        # Reflection uses CHAR for SQLite UUIDs, hence raw hexadecimal values.
        with engine.begin() as connection:
            table_obj = MetaData()
            table_obj.reflect(connection)
            connection.execute(table_obj.tables[table].insert().values(**audit, **values))
    insert('households', id=home_id.hex, name='Local household', currency='USD')
    insert('accounts', id=account_id.hex, household_id=home_id.hex, name='BTC Wallet', type='crypto', balance=Decimal('1.25'), is_active=True)
    insert('categories', id=category_id.hex, household_id=home_id.hex, name='Groceries', kind='expense', is_essential_default=True)
    insert('categories', id=duplicate_id.hex, household_id=home_id.hex, name='GROCERIES', kind='expense', is_essential_default=True)
    insert('transactions', id=transaction_id.hex, household_id=home_id.hex, account_id=account_id.hex, category_id=duplicate_id.hex, date=date(2026, 7, 1), description='Original purchase', amount=Decimal('-42.37'), is_essential=True, is_recurring=False)
    command.upgrade(config, '0024_planner_effective_date')
    rule_id = uuid4()
    insert('recurring_planner_expense_rules', id=rule_id.hex, household_id=home_id.hex, account_id=account_id.hex, display_name='Phone', monthly_projected_amount=Decimal('42.37'))
    command.upgrade(config, 'head')
    engine.dispose()
    reopened = create_database_engine(url)
    try:
        with Session(reopened) as db:
            account = db.get(Account, account_id)
            assert account.asset_symbol == 'BTC'
            assert account.balance == Decimal('1.25000000')
            transaction = db.get(Transaction, transaction_id)
            assert transaction.amount == Decimal('-42.37')
            assert transaction.date == date(2026, 7, 1)
            assert transaction.category_id in {category_id, duplicate_id}
            assert len(db.scalars(select(Category)).all()) == 1
            from app.models import RecurringPlannerExpenseRule
            assert db.get(RecurringPlannerExpenseRule, rule_id).effective_start_date == date(2026, 7, 1)
    finally:
        reopened.dispose()


def test_foreign_keys_uniqueness_cascades_and_rollback(storage):
    url, config = storage
    command.upgrade(config, 'head')
    engine = create_database_engine(url)
    try:
        # Check two physical connections, not just the first pooled connection.
        with engine.connect() as first, engine.connect() as second:
            assert first.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
            assert second.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        with Session(engine) as db:
            home = Household(name='Integrity test')
            db.add(home); db.flush()
            account = Account(household_id=home.id, name='Checking', type='checking', balance=Decimal('100.10'))
            category = Category(household_id=home.id, name='Groceries', kind='expense')
            tag = Tag(household_id=home.id, name='Food')
            db.add_all([account, category, tag]); db.flush()
            txn = Transaction(household_id=home.id, account_id=account.id, category_id=category.id, date=date(2026, 8, 1), description='Food', amount=Decimal('-0.10'))
            db.add(txn); db.flush()
            db.add(TransactionTag(transaction_id=txn.id, tag_id=tag.id)); db.commit()
            home_id, account_id, transaction_id = home.id, account.id, txn.id
            db.add(Category(household_id=home_id, name='GROCERIES', kind='expense'))
            with pytest.raises(IntegrityError): db.commit()
            db.rollback()
            account.balance = Decimal('999.99')
            db.add(Transaction(household_id=home_id, account_id=uuid4(), date=date.today(), description='Invalid parent', amount=1))
            with pytest.raises(IntegrityError): db.commit()
            db.rollback()
            assert db.get(Account, account_id).balance == Decimal('100.10000000')
            db.delete(category); db.commit(); db.expire_all()
            assert db.get(Transaction, transaction_id).category_id is None
            db.delete(account); db.commit(); db.expire_all()
            assert db.get(Transaction, transaction_id) is None
            assert db.scalars(select(TransactionTag)).all() == []
    finally:
        engine.dispose()


def test_failed_upgrade_rolls_back_schema_and_version(storage):
    url, config = storage
    command.upgrade(config, '0001_initial')
    engine = create_database_engine(url)
    # Simulate invalid data from an older installation without FK enforcement.
    import sqlite3
    with sqlite3.connect(engine.url.database) as connection:
        connection.execute("INSERT INTO accounts (id,household_id,name,type,balance,is_active,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)", (uuid4().hex, uuid4().hex, 'Orphan', 'checking', 1, 1, '2026-07-01', '2026-07-01'))
    with pytest.raises(RuntimeError, match='invalid foreign keys'):
        command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == '0001_initial'
        assert 'data_connections' not in inspect(connection).get_table_names()
        assert 'connection_id' not in {column['name'] for column in inspect(connection).get_columns('accounts')}
    engine.dispose()


def test_api_import_financial_totals_and_reopen(storage):
    url, config = storage
    command.upgrade(config, 'head')
    engine = create_database_engine(url)
    def database_session():
        with Session(engine, autoflush=False) as db:
            yield db
    app.dependency_overrides[get_db] = database_session
    credentials = {'email': 'desktop@example.com', 'password': 'Desktop-test-123'}
    try:
        with TestClient(app) as client:
            response = client.post('/api/v1/auth/register', json={**credentials, 'display_name': 'Desktop'})
            assert response.status_code == 200, response.text
            client.headers['Authorization'] = f'Bearer {response.json()["access_token"]}'
            response = client.post('/api/v1/accounts', json={'name': 'Checking', 'type': 'checking', 'balance': 0})
            assert response.status_code == 200, response.text
            account_id = response.json()['id']
            today = date.today().isoformat()
            csv = f'date,description,amount\n{today},Paycheck,1000.25\n{today},Groceries,-42.37\n{today},Small purchase,-0.10\n'
            for expected in (3, 0):
                response = client.post(f'/api/v1/connections/csv/{account_id}', files={'file': ('statement.csv', csv, 'text/csv')})
                assert response.status_code == 200, response.text
                assert response.json()['imported'] == expected
            before = client.get('/api/v1/dashboard')
            assert before.status_code == 200, before.text
            totals = before.json()
            assert totals['monthly_income'] == pytest.approx(1000.25)
            assert totals['monthly_expenses'] == pytest.approx(42.47)
            assert totals['monthly_savings'] == pytest.approx(957.78)
            for path in ['/available-cash-planner', '/reports', '/forecast', '/category-tracker', '/goals']:
                response = client.get('/api/v1' + path)
                assert response.status_code == 200, (path, response.text)
        engine.dispose()
        engine = create_database_engine(url)
        with TestClient(app) as client:
            response = client.post('/api/v1/auth/login', json=credentials)
            assert response.status_code == 200, response.text
            client.headers['Authorization'] = f'Bearer {response.json()["access_token"]}'
            after = client.get('/api/v1/dashboard').json()
            for key in ('monthly_income', 'monthly_expenses', 'monthly_savings'):
                assert after[key] == totals[key]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
