"""Portable local snapshots. Restore runs only with the desktop storage lock held."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
import zipfile

LIMIT = 1024 * 1024 * 1024


def sync_directory(directory):
    if os.name != 'nt':
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def publish(source, destination, replace=False):
    with open(source, 'rb') as stream:
        os.fsync(stream.fileno())
    if replace:
        os.replace(source, destination)
    else:
        os.link(source, destination)
    sync_directory(Path(destination).parent)


def revision(database):
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('The backup database failed its integrity check.')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('The backup database has invalid references.')
        rows = db.execute('SELECT version_num FROM alembic_version').fetchall()
        if len(rows) != 1:
            raise ValueError('The database has no supported migration revision.')
        return rows[0][0]


def digest(file):
    with open(file, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create_backup(directory, destination):
    from .desktop_runtime import prepare_storage
    directory, destination = Path(directory).resolve(), Path(destination).resolve()
    database, _ = prepare_storage(directory)
    if destination.suffix != '.pfosbackup':
        raise ValueError('Choose a filename ending in .pfosbackup.')
    if destination.exists():
        raise ValueError('That backup already exists. Choose a new filename.')
    with tempfile.TemporaryDirectory(prefix='.pfos-backup-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        snapshot = stage / 'pfos.db'
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
        shutil.copyfile(directory / 'runtime.json', stage / 'runtime.json')
        if snapshot.stat().st_size > LIMIT or (stage / 'runtime.json').stat().st_size > 65536:
            raise ValueError('Local data exceeds the supported backup size limit.')
        manifest = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'revision': revision(snapshot),
                    'sha256': {name: digest(stage / name) for name in ('pfos.db', 'runtime.json')}}
        archive = stage / 'backup.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name in ('pfos.db', 'runtime.json'):
                bundle.write(stage / name, name)
            bundle.writestr('manifest.json', json.dumps(manifest))
        archive.chmod(0o600)
        publish(archive, destination)
    return str(destination)


def unpack_backup(archive, stage):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from .desktop_runtime import prepare_storage
    with zipfile.ZipFile(archive) as bundle:
        if sorted(bundle.namelist()) != ['manifest.json', 'pfos.db', 'runtime.json']:
            raise ValueError('Not a supported PFOS backup.')
        for name in bundle.namelist():
            maximum = LIMIT if name == 'pfos.db' else 65536
            if bundle.getinfo(name).file_size > maximum:
                raise ValueError('Backup exceeds the supported size limit.')
            with bundle.open(name) as source, open(stage / name, 'wb') as target:
                shutil.copyfileobj(source, target)
        manifest = json.loads((stage / 'manifest.json').read_text())
        if manifest.get('format') != 1:
            raise ValueError('Unsupported PFOS backup version.')
        for name in ('pfos.db', 'runtime.json'):
            if digest(stage / name) != manifest.get('sha256', {}).get(name):
                raise ValueError('Backup checksum mismatch; no data was replaced.')
    database, _ = prepare_storage(stage)
    actual = revision(database)
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'alembic'))
    known = {item.revision for item in ScriptDirectory.from_config(config).walk_revisions()}
    if actual != manifest.get('revision') or actual not in known:
        raise ValueError('This backup requires a different PFOS version.')


def install_pair(stage, directory):
    # No SQLite connection may be open here. Startup rolls back an interrupted pair.
    for suffix in ('-wal', '-shm', '-journal'):
        (directory / ('pfos.db' + suffix)).unlink(missing_ok=True)
    for name in ('pfos.db', 'runtime.json'):
        staged = stage / name
        staged.chmod(0o600)
        publish(staged, directory / name, replace=True)


def recovery_backup(directory, label):
    backups = directory / 'backups'
    backups.mkdir(mode=0o700, exist_ok=True)
    name = label + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.pfosbackup'
    return Path(create_backup(directory, backups / name))


def recover_interrupted_restore(directory):
    directory = Path(directory).resolve()
    marker = directory / 'restore.pending'
    if not marker.exists():
        return
    details = json.loads(marker.read_text())
    name = details['recovery']
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError('Invalid restore recovery marker; no data was replaced.')
    with tempfile.TemporaryDirectory(prefix='.pfos-recover-', dir=directory) as temporary:
        stage = Path(temporary)
        if details.get('raw'):
            original = directory / 'backups' / name
            for item in ('pfos.db', 'runtime.json', 'pfos.db-wal', 'pfos.db-shm', 'pfos.db-journal'):
                if (original / item).exists():
                    shutil.copyfile(original / item, stage / item)
                    (stage / item).chmod(0o600)
                    publish(stage / item, directory / item, replace=True)
                else:
                    (directory / item).unlink(missing_ok=True)
            sync_directory(directory)
        else:
            unpack_backup(directory / 'backups' / name, stage)
            install_pair(stage, directory)
    marker.unlink()
    sync_directory(directory)


def restore_backup(directory, archive):
    from .desktop_runtime import write_runtime_file
    directory = Path(directory).resolve()
    recover_interrupted_restore(directory)
    with tempfile.TemporaryDirectory(prefix='.pfos-restore-', dir=directory) as temporary:
        stage = Path(temporary)
        unpack_backup(archive, stage)  # Validate before changing the live database.
        raw = False
        try:
            if not (directory / 'pfos.db').exists() or not (directory / 'runtime.json').exists():
                raise ValueError('Incomplete current data')
            recovery = recovery_backup(directory, 'before-restore')
        except (ValueError, RuntimeError, sqlite3.DatabaseError):
            # Preserve damaged/incomplete originals byte-for-byte for manual recovery.
            # Disk/permission errors are deliberately not caught: fail before replacement.
            recovery = directory / 'backups' / ('before-restore-raw-' + uuid.uuid4().hex)
            recovery.mkdir(parents=True, mode=0o700)
            for name in ('pfos.db', 'runtime.json', 'pfos.db-wal', 'pfos.db-shm', 'pfos.db-journal'):
                if (directory / name).exists():
                    shutil.copyfile(directory / name, recovery / name)
                    (recovery / name).chmod(0o600)
                    with open(recovery / name, 'rb') as stream:
                        os.fsync(stream.fileno())
            sync_directory(recovery)
            sync_directory(recovery.parent)
            raw = True
        marker = directory / 'restore.pending'
        write_runtime_file(marker, {'recovery': recovery.name, 'raw': raw})
        try:
            install_pair(stage, directory)
            marker.unlink()
            sync_directory(directory)
        except Exception:
            recover_interrupted_restore(directory)
            raise
    return str(recovery)
