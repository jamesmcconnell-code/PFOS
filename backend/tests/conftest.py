"""Optional full-suite verification against migrated SQLite files."""
from pathlib import Path
import shutil

import pytest
from alembic import command
from alembic.config import Config

from app.config import settings
from app.database import create_database_engine


def pytest_addoption(parser):
    parser.addoption('--migrated-sqlite', action='store_true',
                     help='Run existing database scenarios against migrated SQLite files with foreign keys enabled')


@pytest.fixture(scope='session')
def migrated_template(tmp_path_factory):
    path = tmp_path_factory.mktemp('sqlite-template') / 'template.db'
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'alembic'))
    previous = settings.database_url
    try:
        settings.database_url = f'sqlite:///{path}'
        command.upgrade(config, 'head')
    finally:
        settings.database_url = previous
    return path


@pytest.fixture(autouse=True)
def use_migrated_sqlite(request, monkeypatch, tmp_path):
    if not request.config.getoption('--migrated-sqlite') or not hasattr(request.module, 'create_engine'):
        yield
        return
    template = request.getfixturevalue('migrated_template')
    engines = []
    def migrated_engine(url, **kwargs):
        assert url == 'sqlite://' and not kwargs, 'Add explicit support for this test engine configuration'
        path = tmp_path / f'household-{len(engines)}.db'
        shutil.copyfile(template, path)
        engine = create_database_engine(f'sqlite:///{path}')
        engines.append(engine)
        return engine
    monkeypatch.setattr(request.module, 'create_engine', migrated_engine)
    try:
        yield
    finally:
        for engine in engines:
            engine.dispose()
