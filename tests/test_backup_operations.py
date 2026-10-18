import hashlib
import json
import tarfile

import pytest
from scripts import backup


def manifest(tmp_path):
    names = ['pgdata.tar.gz', 'qdrant.tar.gz', 'maildata.tar.gz', 'local.tar.gz']
    for name in names:
        (tmp_path / name).write_bytes(b'synthetic')
    value = {'version': 1, 'files': {name: backup.digest(tmp_path / name) for name in names}}
    (tmp_path / 'manifest.json').write_text(json.dumps(value))


def test_detects_corruption_and_unsafe_manifest(tmp_path):
    manifest(tmp_path)
    assert backup.verify(tmp_path)['version'] == 1
    (tmp_path / 'pgdata.tar.gz').write_bytes(b'corrupted')
    with pytest.raises(ValueError):
        backup.verify(tmp_path)
    (tmp_path / 'manifest.json').write_text(json.dumps({'version': 1, 'files': {'../secret': 'x'}}))
    with pytest.raises(ValueError):
        backup.verify(tmp_path)


def test_restore_refuses_existing_volumes_before_creating_files(tmp_path, monkeypatch):
    manifest(tmp_path)
    monkeypatch.setattr(backup, 'run', lambda *args: 'recovery_pgdata')
    with pytest.raises(ValueError, match='Volume existente'):
        backup.restore(tmp_path, tmp_path / 'new', 'recovery')
    assert not (tmp_path / 'new').exists()


def test_backup_restarts_previous_services_after_archive_failure(tmp_path, monkeypatch):
    calls = []
    def run(*args):
        calls.append(args)
        if args[:2] == ('docker', 'inspect'):
            return json.dumps([{'Mounts':[{'Type':'volume','Name':'test_volume'}]}])
        if '-aq' in args:
            return 'test_container'
        if '--status' in args:
            return '' if any('stop' in c for c in calls) else 'backend\npostgres'
        if args[:2] == ('docker', 'run'):
            raise RuntimeError('synthetic archive failure')
        return ''
    monkeypatch.setattr(backup, 'run', run)
    with pytest.raises(RuntimeError):
        backup.backup(tmp_path / 'new')
    assert calls[-1] == ('docker', 'compose', 'start', 'backend', 'postgres')


def test_link_backup_rejected():
    info = tarfile.TarInfo('link')
    info.type = tarfile.SYMTYPE
    with pytest.raises(ValueError):
        backup.archive_filter(info)
