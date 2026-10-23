"""Shared local document library. Only administrator-mounted roots are browsable."""
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4, UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.txt', '.md', '.csv'}
def configured_limit(name, default, maximum):
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= maximum:
        raise ValueError(f'{name} trebuie să fie între 1 și {maximum}.')
    return value


MAX_BYTES = configured_limit('SOURCE_MAX_FILE_MB', 250, 1024) * 1024 * 1024
MAX_FOLDER_BYTES = configured_limit('SOURCE_MAX_FOLDER_GB', 100, 10000) * 1024 ** 3
MAX_FILES = configured_limit('SOURCE_MAX_FILES', 50000, 1000000)
router = APIRouter(prefix='/sources')


def root(kind):
    return Path(os.getenv({'local': 'CLIENT_FILES_ROOT', 'upload': 'SOURCE_UPLOAD_ROOT', 'drive': 'DRIVE_MIRROR_ROOT'}[kind],
                          {'local': '/data/client-files', 'upload': '/data/source-uploads', 'drive': '/data/drive-mirror'}[kind]))


def connect():
    path = Path(os.getenv('SOURCE_STATE_ROOT', '/data/source-state'))
    path.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path / 'sources.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, name TEXT, kind TEXT, path TEXT, status TEXT DEFAULT 'pending', checked REAL, error TEXT);
      CREATE UNIQUE INDEX IF NOT EXISTS source_location ON sources(kind,path);
      CREATE TABLE IF NOT EXISTS files(source TEXT, path TEXT, digest TEXT, doc_id TEXT, status TEXT, updated REAL, error TEXT, PRIMARY KEY(source,path));
      CREATE TABLE IF NOT EXISTS worker(id INTEGER PRIMARY KEY, heartbeat REAL);
      CREATE TABLE IF NOT EXISTS source_removals(source TEXT PRIMARY KEY, requested REAL);
      CREATE TABLE IF NOT EXISTS file_removals(source TEXT, path TEXT, requested REAL, cleaned INTEGER DEFAULT 0, PRIMARY KEY(source,path));
    ''')
    return db


def safe_path(base, relative):
    """No absolute paths, traversal, hidden entries or symlink/reparse escapes."""
    if not relative or '\\' in relative or ':' in relative or '\x00' in relative:
        raise ValueError('Cale invalidă.')
    parts = PurePosixPath(relative).parts
    if PurePosixPath(relative).is_absolute() or any(p in ('.', '..') or p.startswith('.') for p in parts):
        raise ValueError('Cale invalidă.')
    candidate = base
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
            raise ValueError('Legăturile simbolice nu sunt acceptate.')
    if not candidate.resolve().is_relative_to(base.resolve()):
        raise ValueError('Cale în afara folderului autorizat.')
    return candidate


def mutation(request):
    # Every mutation uses fetch with non-simple headers; no cross-origin CORS enabled.
    if request.headers.get('x-source-action') != '1':
        raise HTTPException(403, 'Acțiune permisă doar din aplicație.')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Origine neautorizată.')


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['local', 'upload', 'drive']
    path: str = Field(default='', max_length=500)


@router.get('')
def listing():
    db = connect()
    try:
        rows = []
        for source in db.execute('SELECT * FROM sources WHERE id NOT IN (SELECT source FROM source_removals) ORDER BY name,id'):
            item = dict(source)
            visible = 'source=? AND NOT EXISTS (SELECT 1 FROM file_removals r WHERE r.source=files.source AND r.path=files.path)'
            item['counts'] = dict(db.execute(f'SELECT status,count(*) FROM files WHERE {visible} GROUP BY status', (source['id'],)).fetchall())
            item['files'] = [dict(f) for f in db.execute(f'SELECT path,doc_id,status,updated,error FROM files WHERE {visible} ORDER BY updated DESC LIMIT 50', (source['id'],))]
            rows.append(item)
        worker = db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
        cleanup_pending = db.execute('SELECT count(*) FROM file_removals WHERE cleaned=0').fetchone()[0] + db.execute('SELECT count(*) FROM source_removals').fetchone()[0]
        return {'sources': rows, 'cleanup_pending': cleanup_pending, 'worker_active': bool(worker and time.time() - worker[0] < 120), 'formats': sorted(EXTENSIONS), 'poll_seconds': 30, 'limits': {'file_bytes': MAX_BYTES, 'folder_bytes': MAX_FOLDER_BYTES, 'files': MAX_FILES}}
    finally:
        db.close()


@router.delete('/{sid}')
def remove_source(sid: UUID, request: Request):
    """Withdraw immediately; the worker cleans the index and uploaded copies."""
    mutation(request)
    db = connect()
    try:
        source = db.execute('SELECT * FROM sources WHERE id=?', (str(sid),)).fetchone()
        if not source:
            raise HTTPException(404, 'Sursă inexistentă.')
        db.execute('INSERT OR IGNORE INTO source_removals VALUES(?,?)', (str(sid), time.time()))
        db.commit()
        if source['kind'] == 'drive':
            # Stop future syncs; never delete files in the remote Drive folder.
            config = Path(os.getenv('DRIVE_CONFIG_ROOT', '/data/drive-config'))
            (config / (str(sid) + '.json')).unlink(missing_ok=True)
        return {'ok': True, 'status': 'removed'}
    finally:
        db.close()


def removal_requested(db, sid):
    return bool(db.execute('SELECT 1 FROM source_removals WHERE source=?', (sid,)).fetchone())


def file_removal_requested(db, sid, path):
    return bool(db.execute('SELECT 1 FROM file_removals WHERE source=? AND path=?', (sid, path)).fetchone())


@router.post('/{sid}/retry')
def retry_source(sid: UUID, request: Request):
    mutation(request)
    db = connect()
    try:
        if removal_requested(db, str(sid)) or not db.execute('SELECT 1 FROM sources WHERE id=?', (str(sid),)).fetchone():
            raise HTTPException(404, 'Sursă inexistentă.')
        result = db.execute("UPDATE files SET status='pending',updated=0,error=NULL WHERE source=? AND status='error' AND NOT EXISTS (SELECT 1 FROM file_removals r WHERE r.source=files.source AND r.path=files.path)", (str(sid),))
        db.execute("UPDATE sources SET status='pending',error=NULL WHERE id=?", (str(sid),))
        db.commit()
        return {'ok': True, 'queued': result.rowcount}
    finally:
        db.close()


@router.delete('/{sid}/files/{identifier}')
def remove_file(sid: UUID, identifier: str, request: Request):
    """Exclude one document immediately, preserving the source and all other files."""
    mutation(request)
    db = connect()
    try:
        source = db.execute('SELECT 1 FROM sources WHERE id=?', (str(sid),)).fetchone()
        row = db.execute('SELECT path FROM files WHERE source=? AND doc_id=?', (str(sid), identifier)).fetchone()
        if not source or removal_requested(db, str(sid)) or not row:
            raise HTTPException(404, 'Document inexistent în acest folder.')
        db.execute('INSERT OR IGNORE INTO file_removals(source,path,requested) VALUES(?,?,?)',
                   (str(sid), row['path'], time.time()))
        db.commit()
        return {'ok': True, 'status': 'removed'}
    finally:
        db.close()


@router.get('/folders')
def folders(path: str = ''):
    base = root('local')
    try:
        folder = safe_path(base, path) if path else base
        if not folder.is_dir():
            return {'folders': [], 'configured': False}
        children = []
        for child in sorted(folder.iterdir()):
            if child.name.startswith('.'):
                continue
            try:
                rel = child.relative_to(base).as_posix()
                if safe_path(base, rel).is_dir():
                    children.append({'name': child.name, 'path': rel})
            except ValueError:
                continue
        return {'folders': children[:200], 'configured': True}
    except (ValueError, OSError):
        raise HTTPException(400, 'Folder inaccesibil.') from None


@router.post('')
def create(body: SourceIn, request: Request):
    mutation(request)
    sid = str(uuid4())
    path = body.path
    if body.kind == 'local':
        try:
            if not safe_path(root('local'), path).is_dir():
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'Selectează un folder din lista autorizată.') from None
    elif body.kind == 'drive':
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}', path):
            raise HTTPException(422, 'Introdu ID-ul folderului Google Drive, nu adresa URL.')
    else:
        path = sid
        (root('upload') / sid).mkdir(parents=True, exist_ok=True)
    db = connect()
    try:
        db.execute('INSERT INTO sources(id,name,kind,path) VALUES(?,?,?,?)', (sid, body.name, body.kind, path))
        if body.kind == 'drive':
            # Only IDs cross into the network-enabled service, never local source names.
            config_root = Path(os.getenv('DRIVE_CONFIG_ROOT', '/data/drive-config'))
            config_root.mkdir(parents=True, exist_ok=True)
            tmp = config_root / (sid + '.tmp')
            tmp.write_text(json.dumps({'source_id': sid, 'folder_id': path}), encoding='utf-8')
            tmp.replace(config_root / (sid + '.json'))
        db.commit()
        return {'id': sid}
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Acest folder este deja conectat.') from None
    finally:
        db.close()


@router.post('/{sid}/upload')
async def upload(sid: UUID, request: Request, path: str):
    mutation(request)
    db = connect()
    try:
        source = db.execute("SELECT * FROM sources WHERE id=? AND kind='upload' AND id NOT IN (SELECT source FROM source_removals)", (str(sid),)).fetchone()
        if not source:
            raise HTTPException(404, 'Folder de încărcare inexistent.')
        if file_removal_requested(db, str(sid), path):
            raise HTTPException(409, 'Document eliminat din această sursă. Pentru a-l adăuga din nou, încarcă folderul ca sursă nouă.')
    finally:
        db.close()
    try:
        target = safe_path(root('upload') / str(sid), path)
    except ValueError:
        raise HTTPException(422, 'Cale de fișier invalidă.') from None
    if target.suffix.lower() not in EXTENSIONS:
        raise HTTPException(415, 'Format neacceptat.')
    existing = [p for p in (root('upload') / str(sid)).rglob('*') if p.is_file() and not p.name.startswith('.') and p != target]
    if len(existing) >= MAX_FILES:
        raise HTTPException(413, f'Maximum {MAX_FILES:,} de fișiere per folder încărcat.')
    remaining = min(MAX_BYTES, MAX_FOLDER_BYTES - sum(p.stat().st_size for p in existing))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.' + str(uuid4()) + '.part')
    total = 0
    digest = hashlib.sha256()
    try:
        with temporary.open('wb') as out:
            async for chunk in request.stream():
                total += len(chunk)
                if total > remaining:
                    raise HTTPException(413, f'Limită: {MAX_BYTES // 1024 ** 2} MB per fișier și {MAX_FOLDER_BYTES // 1024 ** 3} GB per folder încărcat.')
                out.write(chunk)
                digest.update(chunk)
        if not total:
            raise HTTPException(422, 'Fișier gol.')
        db = connect()
        try:
            # Serialize publication with removal and register before the worker runs.
            db.execute('BEGIN IMMEDIATE')
            if removal_requested(db, str(sid)) or not db.execute('SELECT 1 FROM sources WHERE id=?', (str(sid),)).fetchone():
                raise HTTPException(404, 'Folderul a fost eliminat din bibliotecă.')
            if file_removal_requested(db, str(sid), path):
                raise HTTPException(409, 'Documentul a fost eliminat din această sursă.')
            temporary.replace(target)
            db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)',
                       (str(sid), path, digest.hexdigest(), doc_id(str(sid), path), 'pending', time.time(), None))
            db.execute("UPDATE sources SET status='pending',error=NULL WHERE id=?", (str(sid),))
            db.commit()
        finally:
            db.close()
    finally:
        temporary.unlink(missing_ok=True)
    return {'ok': True, 'status': 'pending'}


def doc_id(source, path):
    return 'SRC-' + hashlib.sha256((source + '/' + path).encode()).hexdigest()[:24]


def content_digest(path):
    digest, total = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_BYTES:
                raise ValueError('Fișier peste limita de dimensiune.')
            digest.update(chunk)
    return digest.hexdigest()



def current_document(identifier, revision):
    """Fail closed for managed sources when watcher is offline or content changed."""
    if not identifier.startswith('SRC-'):
        return True
    db = connect()
    try:
        worker = db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
        if not worker or time.time() - worker[0] > 120:
            return False
        row = db.execute('SELECT f.*,s.kind,s.path AS source_path FROM files f JOIN sources s ON s.id=f.source WHERE f.doc_id=? AND f.status=? AND s.id NOT IN (SELECT source FROM source_removals) AND NOT EXISTS (SELECT 1 FROM file_removals r WHERE r.source=f.source AND r.path=f.path)', (identifier, 'indexed')).fetchone()
        if not row or row['digest'] != revision:
            return False
        base = safe_path(root(row['kind']), row['source_path'] if row['kind'] != 'drive' else row['source'])
        if row['kind'] == 'drive':
            manifest = json.loads((base / '.sync.json').read_text(encoding='utf-8'))
            if manifest.get('status') != 'ready' or time.time() - manifest.get('checked', 0) > 600:
                return False
        path = safe_path(base, row['path'])
        if path.stat().st_size > MAX_BYTES:
            return False
        return content_digest(path) == revision
    except (OSError, ValueError):
        return False
    finally:
        db.close()
