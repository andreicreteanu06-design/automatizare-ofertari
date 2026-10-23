import subprocess
import time

import pytest
from qdrant_client import QdrantClient

from app import sources
from app.ingest import source_watch
from app.ingest.diagnostics import retry_errors
from app.ingest.pdf import Chunk, DocMeta
from app.rag import index as rag_index
from tests.test_retrieval import FakeEmbedder
from tests.test_sources import env


@pytest.mark.parametrize('whole_folder', [False, True])
def test_real_qdrant_points_disappear_on_file_and_folder_removal(env, monkeypatch, whole_folder):
    client, tmp = env
    qdrant = QdrantClient(':memory:')
    monkeypatch.setattr(qdrant, 'close', lambda: None)
    monkeypatch.setattr(rag_index, 'qdrant_client', lambda: qdrant)
    sid = client.post('/sources', json={'kind': 'upload', 'name': 'Lifecycle'}).json()['id']
    for name in ('remove.txt', 'keep.txt'):
        client.post(f'/sources/{sid}/upload', params={'path': name}, content=b'PART123 masa 12 kg')
        path = tmp / 'uploads' / sid / name
        import os
        os.utime(path, (time.time() - 30,) * 2)
    db = sources.connect()
    db.execute('INSERT INTO worker VALUES(1,?)', (time.time(),)); db.commit()
    source = db.execute('SELECT * FROM sources WHERE id=?', (sid,)).fetchone()
    embedder = FakeEmbedder()
    def index(path, identifier, revision):
        meta = DocMeta(identifier, 'Test', '', 'Text', revision)
        chunks = [Chunk(identifier, i, 'text', i + 1, i + 1, None, f'PART123 masa {12+i} kg') for i in range(2)]
        rag_index.index_chunks(qdrant, embedder, chunks, meta)
    source_watch.scan_source(db, source, index=index)
    assert qdrant.count(rag_index.COLLECTION).count == 4
    identifier = sources.doc_id(sid, 'remove.txt')
    endpoint = f'/sources/{sid}' + ('' if whole_folder else f'/files/{identifier}')
    assert client.delete(endpoint).status_code == 200
    assert client.get('/sources').json()['cleanup_pending'] > 0
    # Excluded immediately even before the worker physically deletes the vectors.
    hits = rag_index.vector_search(qdrant, embedder, 'PART123 masa', 10)
    assert identifier not in [h['doc_id'] for h in hits]
    source_watch.scan_source(db, source)
    assert qdrant.count(rag_index.COLLECTION).count == (0 if whole_folder else 2)
    assert client.get('/sources').json()['cleanup_pending'] == 0
    if not whole_folder:
        remaining, _ = qdrant.scroll(rag_index.COLLECTION, limit=20)
        assert {point.payload['doc_id'] for point in remaining} == {sources.doc_id(sid, 'keep.txt')}
    db.close()


@pytest.mark.parametrize('returncode,stderr,code', [(1, b'OFERTARE_INDEX_ERROR=missing_model\n', 'missing_model'), (-9, b'', 'memory'), (1, b'private secret text', 'conversion')])
def test_subprocess_failure_is_actionable_without_exposing_raw_logs(monkeypatch, returncode, stderr, code):
    monkeypatch.setattr(source_watch.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess([], returncode, b'', stderr))
    with pytest.raises(source_watch.IndexFailure) as error:
        source_watch.index_document('file.pdf', 'SRC-test', 'digest')
    assert error.value.code == code
    assert 'private secret' not in str(error.value)


def test_indexing_timeout_is_reported(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('process', 1800)
    monkeypatch.setattr(source_watch.subprocess, 'run', timeout)
    with pytest.raises(source_watch.IndexFailure) as error:
        source_watch.index_document('file.pdf', 'SRC-test', 'digest')
    assert error.value.code == 'timeout'


def test_retry_does_not_requeue_deleted_or_indexing_documents(env):
    client, _ = env
    sid = client.post('/sources', json={'kind': 'upload', 'name': 'Retry'}).json()['id']
    for name in ('error.txt', 'removed.txt', 'running.txt'):
        client.post(f'/sources/{sid}/upload', params={'path': name}, content=b'PART123')
    db = sources.connect()
    db.execute("UPDATE files SET status='error',error='failed'")
    db.execute("UPDATE files SET status='indexing' WHERE path='running.txt'"); db.commit()
    client.delete(f'/sources/{sid}/files/{sources.doc_id(sid, "removed.txt")}')
    assert retry_errors(db) == 1
    statuses = dict(db.execute('SELECT path,status FROM files').fetchall())
    assert statuses == {'error.txt': 'pending', 'removed.txt': 'error', 'running.txt': 'indexing'}
    db.execute("UPDATE files SET status='error' WHERE path='error.txt'"); db.commit()
    assert client.post(f'/sources/{sid}/retry', headers={'X-Source-Action': ''}).status_code == 403
    assert client.post(f'/sources/{sid}/retry').json()['queued'] == 1
    client.delete(f'/sources/{sid}')
    assert client.post(f'/sources/{sid}/retry').status_code == 404
    assert retry_errors(db) == 0
    db.close()


def test_failed_preflight_never_requeues_documents(monkeypatch, capsys):
    from app.ingest import diagnostics
    monkeypatch.setattr(diagnostics, 'check_runtime', lambda: [{'component': 'Docling', 'ok': False, 'error_type': 'ImportError'}])
    monkeypatch.setattr(diagnostics, 'connect', lambda: pytest.fail('Do not mutate state after failed preflight'))
    monkeypatch.setattr('sys.argv', ['diagnostics', '--retry'])
    assert diagnostics.main() == 1
    assert 'ok=false' in capsys.readouterr().out
