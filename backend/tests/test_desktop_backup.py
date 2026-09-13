import json
from pathlib import Path
import shutil
import sqlite3
import zipfile

import pytest

from app.desktop_backup import create_backup, restore_backup, recover_interrupted_restore
from app.desktop_runtime import prepare_storage, mark_storage_initialized


@pytest.fixture
def household(tmp_path, migrated_template):
    folder = tmp_path / 'household'
    database, values = prepare_storage(folder)
    shutil.copyfile(migrated_template, database)
    mark_storage_initialized(folder, values)
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE backup_test (value TEXT)')
        db.execute("INSERT INTO backup_test VALUES ('original')")
    return folder


def value(folder):
    with sqlite3.connect(folder / 'pfos.db') as db:
        return db.execute('SELECT value FROM backup_test').fetchone()[0]


def change(folder):
    with sqlite3.connect(folder / 'pfos.db') as db:
        db.execute("UPDATE backup_test SET value='changed'")


def test_backup_restore_and_recovery_copy(household, tmp_path):
    archive = tmp_path / 'saved.pfosbackup'
    secrets = (household / 'runtime.json').read_bytes()
    create_backup(household, archive)
    change(household)
    recovery = restore_backup(household, archive)
    assert value(household) == 'original'
    assert (household / 'runtime.json').read_bytes() == secrets
    assert not (household / 'restore.pending').exists()
    restore_backup(household, recovery)
    assert value(household) == 'changed'
    with pytest.raises(ValueError, match='already exists'):
        create_backup(household, archive)


def test_invalid_backup_preserves_live_data(household, tmp_path):
    archive = tmp_path / 'bad.pfosbackup'
    archive.write_bytes(b'not a backup')
    before = (household / 'pfos.db').read_bytes()
    with pytest.raises(zipfile.BadZipFile):
        restore_backup(household, archive)
    assert (household / 'pfos.db').read_bytes() == before
    assert not (household / 'backups').exists()


def test_tampered_archive_is_refused(household, tmp_path):
    good, bad = tmp_path / 'good.pfosbackup', tmp_path / 'bad.pfosbackup'
    create_backup(household, good)
    with zipfile.ZipFile(good) as source, zipfile.ZipFile(bad, 'w') as target:
        for name in source.namelist():
            data = source.read(name)
            if name == 'runtime.json':
                data = data.replace(b'jwt_secret', b'bad_secret')
            target.writestr(name, data)
    with pytest.raises(ValueError, match='checksum'):
        restore_backup(household, bad)
    assert value(household) == 'original'


def test_process_interruption_rolls_back_on_next_launch(household, tmp_path, monkeypatch):
    import app.desktop_backup as backups
    archive = tmp_path / 'saved.pfosbackup'
    create_backup(household, archive)
    change(household)
    original = backups.publish
    def interrupted(source, destination, replace=False):
        original(source, destination, replace)
        if replace and Path(destination).name == 'pfos.db':
            raise KeyboardInterrupt('Simulated process death between database and secrets')
    monkeypatch.setattr(backups, 'publish', interrupted)
    with pytest.raises(KeyboardInterrupt):
        restore_backup(household, archive)
    assert (household / 'restore.pending').exists()
    monkeypatch.setattr(backups, 'publish', original)
    recover_interrupted_restore(household)
    assert value(household) == 'changed'
    assert not (household / 'restore.pending').exists()


def test_sqlite_snapshot_includes_committed_wal_data(household, tmp_path):
    with sqlite3.connect(household / 'pfos.db') as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute("UPDATE backup_test SET value='in WAL'")
        db.commit()
        archive = tmp_path / 'wal.pfosbackup'
        create_backup(household, archive)
    change(household)
    restore_backup(household, archive)
    assert value(household) == 'in WAL'


def test_known_older_database_is_backed_up_before_upgrade(tmp_path):
    import os
    import subprocess
    import sys
    folder = tmp_path / 'older'
    script = '''
import sys
from pathlib import Path
from app.desktop_runtime import prepare_storage, configure_environment, initialize_database, mark_storage_initialized
from alembic.config import Config
from alembic import command
folder = Path(sys.argv[1])
database, values = prepare_storage(folder)
configure_environment(database, values, 'http://localhost:3000')
config = Config()
config.set_main_option('script_location', str(Path('backend/alembic').resolve()))
command.upgrade(config, '0033_smart_tagging_engine')
mark_storage_initialized(folder, values)
initialize_database()
'''
    # Use the actual revision identifier rather than assuming the filename is its ID.
    migration = Path(__file__).resolve().parents[1] / 'alembic/versions/0033_smart_tagging_engine.py'
    namespace = {}
    exec(migration.read_text(), namespace)
    script = script.replace('0033_smart_tagging_engine', namespace['revision'])
    result = subprocess.run([sys.executable, '-c', script, str(folder)],
                            cwd=Path(__file__).resolve().parents[2], env=os.environ.copy(), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert len(list((folder / 'backups').glob('before-upgrade-*.pfosbackup'))) == 1


@pytest.mark.parametrize('damaged', [False, True])
def test_restore_into_empty_or_damaged_profile(household, tmp_path, damaged):
    archive = tmp_path / 'saved.pfosbackup'
    create_backup(household, archive)
    target = tmp_path / 'target'
    target.mkdir()
    if damaged:
        (target / 'pfos.db').write_bytes(b'damaged original')
        (target / 'runtime.json').write_bytes(b'broken secrets')
    recovery = Path(restore_backup(target, archive))
    assert value(target) == 'original'
    if damaged:
        assert (recovery / 'pfos.db').read_bytes() == b'damaged original'
        assert (recovery / 'runtime.json').read_bytes() == b'broken secrets'
