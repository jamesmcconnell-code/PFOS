"""Local-only lifecycle for the bundled API, isolated from server configuration."""
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
from urllib.parse import urlsplit


def write_runtime_file(path, values, *, replace=False):
    """Publish a complete JSON file, preserving the original on write failure."""
    fd, temporary = tempfile.mkstemp(prefix='.runtime-', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(values, stream)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Publish without overwriting a concurrently created installation.
            os.link(temporary, path)
        if os.name != 'nt':
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_storage(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    database = directory / 'pfos.db'
    config_path = directory / 'runtime.json'
    if not config_path.exists():
        if any((directory / name).exists() for name in ('pfos.db', 'pfos.db-wal', 'pfos.db-shm', 'pfos.db-journal')):
            raise RuntimeError('Local database exists but runtime.json is missing. Restore its original secrets before opening PFOS.')
        values = {'storage_version': 1, 'database_initialized': False,
                  'jwt_secret': secrets.token_urlsafe(48), 'credential_encryption_key': secrets.token_urlsafe(48)}
        write_runtime_file(config_path, values)
    try:
        values = json.loads(config_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError('Local runtime.json is invalid. Restore its original secrets before opening PFOS.') from None
    if not isinstance(values, dict) or any(not isinstance(values.get(key), str) or len(values[key]) < 32
                                         for key in ('jwt_secret', 'credential_encryption_key')):
        raise RuntimeError('Local runtime.json is invalid. Restore its original secrets before opening PFOS.')
    if type(values.get('storage_version', 1)) is not int or values.get('storage_version', 1) != 1:
        raise RuntimeError('This local storage format requires a different PFOS version. No files were replaced.')
    if 'database_initialized' in values and type(values['database_initialized']) is not bool:
        raise RuntimeError('Local runtime.json has an invalid database state. No files were replaced.')
    # Legacy step-3 secrets imply an existing installation. Only an explicitly
    # unfinished first launch may initialize a missing/empty database.
    if values.get('database_initialized', True) and (not database.is_file() or database.stat().st_size == 0):
        raise RuntimeError('Local database is missing or empty. Restore the original database; PFOS will not create a replacement.')
    if os.name != 'nt':
        config_path.chmod(0o600)
    return database, values


def mark_storage_initialized(directory, values):
    """Called under the storage lock only after migrations/validation succeed."""
    if values.get('database_initialized') is True and values.get('storage_version') == 1:
        return
    write_runtime_file(Path(directory) / 'runtime.json',
                       {**values, 'storage_version': 1, 'database_initialized': True}, replace=True)


def lock_storage(directory):
    """Hold an OS lock for the process lifetime; stale files are harmless."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(directory / '.backend.lock', 'a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            lock.write(b'\0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise RuntimeError('This PFOS data folder is already open in another backend.') from None
    return lock


def configure_environment(database, values, origin):
    # Force local settings even if launched from a server-configured terminal.
    os.environ.update(DATABASE_URL='sqlite:///' + database.as_posix(),
                      JWT_SECRET=values['jwt_secret'],
                      CREDENTIAL_ENCRYPTION_KEY=values['credential_encryption_key'],
                      CORS_ORIGINS=origin, PFOS_DESKTOP_RUNTIME='1')
    for name in ('PLAID_CLIENT_ID', 'PLAID_SECRET', 'PLAID_ENVIRONMENT'):
        os.environ.pop(name, None)


def initialize_database():
    from alembic import command
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect
    from .database import engine
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'alembic'))
    with engine.connect() as connection:
        if connection.exec_driver_sql('PRAGMA quick_check').scalar() != 'ok':
            raise RuntimeError('Local database integrity check failed. Restore it before opening PFOS.')
        tables = inspect(connection).get_table_names()
        revisions = MigrationContext.configure(connection).get_current_heads()
    head = ScriptDirectory.from_config(config).get_current_head()
    if not tables:
        command.upgrade(config, 'head')
    elif revisions != (head,):
        # Automatic existing-data upgrades require the backup workflow in step 7.
        raise RuntimeError('Local database needs a migration. Back it up and upgrade it before opening this PFOS version.')


class DesktopAccess:
    """An ephemeral desktop capability is required in addition to user login."""
    def __init__(self, application, token, origin, host):
        self.application, self.token, self.origin, self.host = application, token, origin, host

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.application(scope, receive, send)
        from starlette.datastructures import Headers
        from starlette.responses import JSONResponse
        headers = Headers(scope=scope)
        origin = headers.get('origin')
        if headers.get('host') != self.host or (origin is not None and origin != self.origin):
            return await JSONResponse({'detail': 'Desktop origin required'}, status_code=403)(scope, receive, send)
        preflight = scope['method'] == 'OPTIONS' and origin == self.origin and headers.get('access-control-request-method')
        if not preflight and not hmac.compare_digest(headers.get('x-pfos-desktop-token', ''), self.token):
            return await JSONResponse({'detail': 'Desktop access required'}, status_code=401)(scope, receive, send)
        return await self.application(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description='PFOS bundled desktop backend')
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--frontend-origin', required=True)
    args = parser.parse_args()
    origin = urlsplit(args.frontend_origin)
    if (origin.scheme != 'http' or origin.hostname not in ('localhost', '127.0.0.1', '::1')
            or origin.username or origin.password or origin.path or origin.query or origin.fragment):
        parser.error('frontend-origin must be a loopback HTTP origin')
    # The launch capability travels through a private pipe, never argv or disk.
    bootstrap = json.loads(sys.stdin.readline(4096))
    token = bootstrap.get('token', '')
    if not isinstance(token, str) or len(token) < 32 or not token.isascii():
        raise RuntimeError('Missing desktop launch capability')
    parent_closed = threading.Event()
    def watch_parent():
        sys.stdin.read()
        parent_closed.set()
    threading.Thread(target=watch_parent, daemon=True).start()
    os.umask(0o077)
    directory = Path(args.data_dir).resolve()
    lock = lock_storage(directory)
    try:
        database, values = prepare_storage(directory)
        configure_environment(database, values, args.frontend_origin)
        os.chdir(directory)
        initialize_database()
        mark_storage_initialized(directory, values)
        if parent_closed.is_set():
            return
        import asyncio
        import uvicorn
        from .main import app
        from .database import engine
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            application = DesktopAccess(app, token, args.frontend_origin, f'127.0.0.1:{port}')
            class DesktopServer(uvicorn.Server):
                async def startup(self, sockets=None):
                    await super().startup(sockets=sockets)
                    if self.started:
                        print(json.dumps({'event': 'pfos-ready', 'url': f'http://127.0.0.1:{port}'}), flush=True)
                async def on_tick(self, counter):
                    if parent_closed.is_set():
                        self.should_exit = True
                    return await super().on_tick(counter)
            server = DesktopServer(uvicorn.Config(application, loop='asyncio', http='h11', ws='none',
                                                 access_log=False, log_level='warning', timeout_graceful_shutdown=3))
            try:
                asyncio.run(server.serve(sockets=[listener]))
            finally:
                engine.dispose()
    finally:
        lock.close()
