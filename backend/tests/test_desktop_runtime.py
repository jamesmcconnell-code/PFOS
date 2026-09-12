import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.desktop_runtime import DesktopAccess, lock_storage, prepare_storage


def test_runtime_secrets_survive_reopening(tmp_path):
    database, first = prepare_storage(tmp_path)
    assert database == tmp_path / 'pfos.db'
    assert len(first['jwt_secret']) >= 32
    assert first['jwt_secret'] != first['credential_encryption_key']
    assert prepare_storage(tmp_path)[1] == first


def test_existing_database_without_secrets_is_never_adopted(tmp_path):
    (tmp_path / 'pfos.db').touch()
    with pytest.raises(RuntimeError, match='original secrets'):
        prepare_storage(tmp_path)
    assert not (tmp_path / 'runtime.json').exists()


def test_corrupt_secrets_are_not_replaced(tmp_path):
    file = tmp_path / 'runtime.json'
    file.write_text(json.dumps({'jwt_secret': 'short'}))
    original = file.read_bytes()
    with pytest.raises(RuntimeError, match='invalid'):
        prepare_storage(tmp_path)
    assert file.read_bytes() == original


def test_storage_has_a_single_owner(tmp_path):
    lock = lock_storage(tmp_path)
    try:
        with pytest.raises(RuntimeError, match='already open'):
            lock_storage(tmp_path)
    finally:
        lock.close()
    lock_storage(tmp_path).close()


def test_desktop_gate_requires_capability_and_expected_origin():
    app = FastAPI()
    @app.get('/health')
    def health(): return {'status': 'ok'}
    client = TestClient(DesktopAccess(app, 'a' * 48, 'http://localhost:3000', 'testserver'))
    assert client.get('/health').status_code == 401
    token = {'X-PFOS-Desktop-Token': 'a' * 48}
    assert client.get('/health', headers=token).status_code == 200
    assert client.get('/health', headers={**token, 'Origin': 'http://untrusted.example'}).status_code == 403
    assert client.get('/health', headers={**token, 'Host': 'untrusted.example'}).status_code == 403
    assert client.get('/health', headers={**token, 'Origin': 'http://localhost:3000'}).status_code == 200


def test_interrupted_first_launch_can_retry_without_changing_secrets(tmp_path):
    database, values = prepare_storage(tmp_path)
    assert values['database_initialized'] is False
    assert not database.exists()
    assert prepare_storage(tmp_path)[1] == values


def test_initialized_database_is_never_silently_recreated(tmp_path):
    from app.desktop_runtime import mark_storage_initialized
    database, values = prepare_storage(tmp_path)
    database.write_bytes(b'original database fixture')
    mark_storage_initialized(tmp_path, values)
    database.unlink()
    original = (tmp_path / 'runtime.json').read_bytes()
    with pytest.raises(RuntimeError, match='missing or empty'):
        prepare_storage(tmp_path)
    assert not database.exists()
    assert (tmp_path / 'runtime.json').read_bytes() == original


def test_empty_initialized_database_is_refused(tmp_path):
    from app.desktop_runtime import mark_storage_initialized
    database, values = prepare_storage(tmp_path)
    database.touch()
    mark_storage_initialized(tmp_path, values)
    with pytest.raises(RuntimeError, match='missing or empty'):
        prepare_storage(tmp_path)
    assert database.stat().st_size == 0


def test_legacy_secrets_are_preserved_when_adopting_storage_state(tmp_path):
    from app.desktop_runtime import mark_storage_initialized
    legacy = {'jwt_secret': 'a' * 48, 'credential_encryption_key': 'b' * 48}
    (tmp_path / 'runtime.json').write_text(json.dumps(legacy))
    (tmp_path / 'pfos.db').write_bytes(b'legacy database fixture')
    _, values = prepare_storage(tmp_path)
    mark_storage_initialized(tmp_path, values)
    upgraded = prepare_storage(tmp_path)[1]
    assert upgraded['database_initialized'] is True
    assert upgraded['jwt_secret'] == legacy['jwt_secret']
    assert upgraded['credential_encryption_key'] == legacy['credential_encryption_key']


def test_future_storage_version_is_refused_without_changes(tmp_path):
    _, values = prepare_storage(tmp_path)
    values['storage_version'] = 999
    file = tmp_path / 'runtime.json'
    file.write_text(json.dumps(values))
    original = file.read_bytes()
    with pytest.raises(RuntimeError, match='different PFOS version'):
        prepare_storage(tmp_path)
    assert file.read_bytes() == original


def test_failed_atomic_update_keeps_original_secrets(tmp_path, monkeypatch):
    from app.desktop_runtime import mark_storage_initialized
    _, values = prepare_storage(tmp_path)
    original = (tmp_path / 'runtime.json').read_bytes()
    def fail(*args): raise OSError('Simulated disk failure')
    monkeypatch.setattr('app.desktop_runtime.os.replace', fail)
    with pytest.raises(OSError, match='disk failure'):
        mark_storage_initialized(tmp_path, values)
    assert (tmp_path / 'runtime.json').read_bytes() == original
    assert list(tmp_path.glob('.runtime-*.tmp')) == []


def test_failed_first_write_never_publishes_partial_secrets(tmp_path, monkeypatch):
    def fail(*args): raise OSError('Simulated disk failure')
    monkeypatch.setattr('app.desktop_runtime.os.fsync', fail)
    with pytest.raises(OSError, match='disk failure'):
        prepare_storage(tmp_path)
    assert not (tmp_path / 'runtime.json').exists()
    assert list(tmp_path.glob('.runtime-*.tmp')) == []


def test_truncated_runtime_file_is_preserved_and_reported(tmp_path):
    file = tmp_path / 'runtime.json'
    file.write_text('{"jwt_secret":')
    with pytest.raises(RuntimeError, match='invalid'):
        prepare_storage(tmp_path)
    assert file.read_text() == '{"jwt_secret":'
