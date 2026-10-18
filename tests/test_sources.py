import json
import os
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import sources
from app.ingest.source_watch import scan_source
from drive_sync.sync import sync
from research_gateway.egress_guard import EgressGuard


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key, name in [('SOURCE_STATE_ROOT', 'state'), ('CLIENT_FILES_ROOT', 'local'), ('SOURCE_UPLOAD_ROOT', 'uploads'), ('DRIVE_MIRROR_ROOT', 'drive'), ('DRIVE_CONFIG_ROOT', 'config')]:
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(key, str(directory))
    (tmp_path / 'local' / 'Technical').mkdir()
    app = FastAPI()
    app.include_router(sources.router)
    return TestClient(app, headers={'X-Source-Action': '1'}), tmp_path


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'C:/secret', 'x/../../secret', '.env', 'a\\b'])
def test_paths_reject_traversal(env, path):
    client, _ = env
    assert client.post('/sources', json={'kind': 'local', 'name': 'Test', 'path': path}).status_code == 422


def test_upload_binary_nested_and_csrf(env):
    client, tmp = env
    assert client.post('/sources', json={'kind': 'upload', 'name': 'Test'}, headers={'X-Source-Action': ''}).status_code == 403
    sid = client.post('/sources', json={'kind': 'upload', 'name': 'Test'}).json()['id']
    assert client.post(f'/sources/{sid}/upload', params={'path': 'nested/file.txt'}, content=b'PART123 5 kg').status_code == 200
    assert (tmp / 'uploads' / sid / 'nested/file.txt').read_bytes() == b'PART123 5 kg'
    assert client.post(f'/sources/{sid}/upload', params={'path': '../secret.txt'}, content=b'x').status_code == 422
    assert client.post(f'/sources/{sid}/upload', params={'path': 'script.exe'}, content=b'x').status_code == 415
    assert client.post(f'/sources/{sid}/upload', params={'path': 'empty.txt'}, content=b'').status_code == 422
    assert not list((tmp / 'uploads').rglob('*.part'))


def test_configured_upload_limits_and_atomic_overwrite(env, monkeypatch):
    client, tmp = env
    monkeypatch.setattr(sources, 'MAX_BYTES', 12)
    monkeypatch.setattr(sources, 'MAX_FOLDER_BYTES', 15)
    monkeypatch.setattr(sources, 'MAX_FILES', 2)
    assert client.get('/sources').json()['limits'] == {'file_bytes': 12, 'folder_bytes': 15, 'files': 2}
    sid = client.post('/sources', json={'kind': 'upload', 'name': 'Test'}).json()['id']
    endpoint = f'/sources/{sid}/upload'
    assert client.post(endpoint, params={'path': 'one.txt'}, content=b'123456789012').status_code == 200
    assert client.post(endpoint, params={'path': 'one.txt'}, content=b'x' * 13).status_code == 413
    assert (tmp / 'uploads' / sid / 'one.txt').read_bytes() == b'123456789012'
    assert client.post(endpoint, params={'path': 'two.txt'}, content=b'1234').status_code == 413
    assert client.post(endpoint, params={'path': 'two.txt'}, content=b'123').status_code == 200
    assert client.post(endpoint, params={'path': 'three.txt'}, content=b'1').status_code == 413
    assert not list((tmp / 'uploads').rglob('*.part'))


def test_upload_above_former_40_mib_limit(env):
    client, tmp = env
    sid = client.post('/sources', json={'kind': 'upload', 'name': 'Arhiva'}).json()['id']
    payload = b'0' * (41 * 1024 * 1024)
    response = client.post(f'/sources/{sid}/upload', params={'path': 'large.pdf'}, content=payload)
    assert response.status_code == 200
    assert (tmp / 'uploads' / sid / 'large.pdf').stat().st_size == len(payload)


def test_large_document_digest_streams_and_preserves_revision(tmp_path, monkeypatch):
    import hashlib
    path = tmp_path / 'large.pdf'
    with path.open('wb') as out:
        out.seek(41 * 1024 * 1024)
        out.write(b'end')
    assert sources.MAX_BYTES >= path.stat().st_size
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    original = Path.open
    reads = []
    class Reader:
        def __enter__(self):
            self.stream = original(path, 'rb')
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size):
            reads.append(size)
            assert size <= 1024 * 1024
            return self.stream.read(size)
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: Reader())
    assert sources.content_digest(path) == expected
    assert len(reads) > 40
    monkeypatch.setattr(sources, 'MAX_BYTES', 1024)
    with pytest.raises(ValueError):
        sources.content_digest(path)


def test_monitor_revisions_deletion_and_freshness(env):
    client, tmp = env
    sid = client.post('/sources', json={'kind': 'local', 'name': 'Technical', 'path': 'Technical'}).json()['id']
    assert client.post('/sources', json={'kind': 'local', 'name': 'Duplicate', 'path': 'Technical'}).status_code == 409
    path = tmp / 'local' / 'Technical' / 'file.txt'
    path.write_text('PART123 5 kg')
    os.utime(path, (time.time() - 30,) * 2)
    db = sources.connect()
    indexed, removed = [], []
    def index(p, docid, digest):
        indexed.append((docid, digest))
    source = db.execute('SELECT * FROM sources WHERE id=?', (sid,)).fetchone()
    db.execute('INSERT INTO worker VALUES(1,?)', (time.time(),)); db.commit()
    scan_source(db, source, index, removed.append)
    assert len(indexed) == 1 and path.exists()
    assert sources.current_document(*indexed[-1])
    scan_source(db, source, index, removed.append)
    assert len(indexed) == 1
    path.write_text('PART123 7 kg')
    assert not sources.current_document(*indexed[-1])
    os.utime(path, (time.time() - 30,) * 2)
    scan_source(db, source, index, removed.append)
    assert indexed[0][0] == indexed[1][0] and indexed[0][1] != indexed[1][1]
    assert sources.current_document(*indexed[-1])
    path.unlink()
    assert not sources.current_document(*indexed[-1])
    scan_source(db, source, index, removed.append)
    assert db.execute('SELECT status FROM files').fetchone()[0] == 'removed'
    db.close()


def test_index_failure_does_not_serve_old_evidence(env):
    client, tmp = env
    sid = client.post('/sources', json={'kind': 'local', 'name': 'Technical', 'path': 'Technical'}).json()['id']
    path = tmp / 'local/Technical/file.txt'
    path.write_text('PART123 5 kg'); os.utime(path, (time.time() - 30,) * 2)
    db = sources.connect()
    def fail(*args):
        raise RuntimeError('bad converter')
    scan_source(db, db.execute('SELECT * FROM sources').fetchone(), fail, lambda _: None)
    row = db.execute('SELECT * FROM files').fetchone()
    assert row['status'] == 'error'
    assert not sources.current_document(row['doc_id'], row['digest'])
    db.close()


def test_symlinks_not_followed(env):
    _, tmp = env
    outside = tmp / 'secret.txt'; outside.write_text('private')
    link = tmp / 'local/Technical/link.txt'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('Symlink privilege unavailable')
    with pytest.raises(ValueError):
        sources.safe_path(tmp / 'local', 'Technical/link.txt')


def test_drive_only_ids_in_network_config(env):
    client, tmp = env
    result = client.post('/sources', json={'kind': 'drive', 'name': 'Private project name', 'path': 'folder12345678'})
    config = json.loads((tmp / 'config' / (result.json()['id'] + '.json')).read_text())
    assert set(config) == {'folder_id', 'source_id'}
    assert 'Private' not in json.dumps(config)


def test_drive_mirror_changes_and_no_delete_on_partial_failure(tmp_path):
    guard = EgressGuard(['confidentialproject'])
    config = {'source_id': '11111111-1111-4111-8111-111111111111', 'folder_id': 'folder12345678'}
    state = {'files': [{'id': 'file12345678', 'name': 'spec.pdf', 'mimeType': 'application/pdf', 'size': '12', 'modifiedTime': 'v1'}], 'fail': False}
    calls = []
    def call(method, params, guard, output=None):
        guard.check(params)
        calls.append((method, params))
        assert method in ('list', 'get', 'export')
        if state['fail']:
            raise RuntimeError('network failure')
        if method == 'list':
            return {'files': state['files']}
        output.write_bytes(b'PDF content')
        return {}
    sync(config, tmp_path, guard, call)
    mirror = tmp_path / config['source_id']
    assert (mirror / 'file12345678.pdf').exists()
    sync(config, tmp_path, guard, call)
    assert len([c for c in calls if c[0] == 'get']) == 1
    state['fail'] = True
    with pytest.raises(RuntimeError):
        sync(config, tmp_path, guard, call)
    assert (mirror / 'file12345678.pdf').exists()
    assert json.loads((mirror / '.sync.json').read_text())['status'] == 'error'
    state.update(fail=False, files=[])
    sync(config, tmp_path, guard, call)
    assert not (mirror / 'file12345678.pdf').exists()
