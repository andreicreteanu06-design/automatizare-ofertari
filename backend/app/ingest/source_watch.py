"""Read-only recursive sources -> current RAG evidence. Never moves client files."""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.sources import EXTENSIONS, MAX_BYTES, MAX_FILES, connect, doc_id, root, safe_path, content_digest


def remove_document(identifier):
    from app.rag.index import COLLECTION, _doc_filter, qdrant_client
    from qdrant_client.models import FilterSelector
    client = qdrant_client()
    try:
        if client.collection_exists(COLLECTION):
            client.delete(COLLECTION, points_selector=FilterSelector(filter=_doc_filter(identifier)), wait=True)
    finally:
        client.close()


def index_document(path, identifier, digest):
    # One subprocess at a time releases Docling/BGE memory after each document.
    result = subprocess.run([sys.executable, '-m', 'app.ingest.source_watch', '--file', str(path), identifier, digest],
                            capture_output=True, timeout=1800)
    if result.returncode:
        raise RuntimeError('Conversia sau indexarea a eșuat. Verifică modelele și formatul documentului.')


def snapshot(folder):
    result = {}
    # os.walk does not follow symlinks; permission errors abort deletion reconciliation.
    def fail(error):
        raise error
    for current, dirs, files in os.walk(folder, followlinks=False, onerror=fail):
        dirs[:] = [d for d in dirs if not d.startswith('.') and not (Path(current) / d).is_symlink()]
        for name in files:
            if name.startswith('.') or Path(name).suffix.lower() not in EXTENSIONS:
                continue
            rel = (Path(current) / name).relative_to(folder).as_posix()
            try:
                path = safe_path(folder, rel)
            except ValueError:
                continue
            stat = path.stat()
            result[rel] = (path, stat)
            if len(result) > MAX_FILES:
                raise ValueError(f'Limita de {MAX_FILES:,} documente per sursă a fost depășită.')
    return result


def scan_source(db, source, index=index_document, remove=remove_document, now=None):
    now = now or time.time()
    sid = source['id']
    folder = safe_path(root(source['kind']), source['path'] if source['kind'] != 'drive' else sid)
    if not folder.is_dir():
        raise ValueError('Folderul nu este disponibil. Verifică montarea sau sincronizarea Drive.')
    if source['kind'] == 'drive':
        manifest = json.loads((folder / '.sync.json').read_text(encoding='utf-8'))
        if manifest.get('status') != 'ready' or now - manifest.get('checked', 0) > 600:
            raise ValueError('Sincronizarea Drive nu este actualizată. Verifică serviciul drive-sync.')
    files = snapshot(folder)
    previous = {r['path']: dict(r) for r in db.execute('SELECT * FROM files WHERE source=?', (sid,))}
    errors = 0
    pending = False
    for rel, (path, stat) in files.items():
        old = previous.get(rel)
        identifier = doc_id(sid, rel)
        if stat.st_size > MAX_BYTES:
            remove(identifier)
            db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)', (sid, rel, '', identifier, 'error', now, f'Fișier peste {MAX_BYTES // 1024 ** 2} MB.'))
            db.commit()
            errors += 1
            continue
        # Delay until copying settles. Existing evidence is withdrawn on observed changes.
        digest = content_digest(path)
        if old and old['digest'] == digest and old['status'] == 'indexed':
            continue
        remove(identifier)
        if now - stat.st_mtime < 10:
            db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)', (sid, rel, digest, identifier, 'pending', now, None))
            db.commit()
            pending = True
            continue
        # Back off malformed documents, while new content retries immediately.
        if old and old['digest'] == digest and old['status'] == 'error' and now - old['updated'] < 300:
            errors += 1
            continue
        db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)', (sid, rel, digest, identifier, 'indexing', now, None))
        db.commit()
        try:
            index(path, identifier, digest)
            if content_digest(path) != digest:
                raise ValueError('Fișier modificat în timpul procesării; va fi reluat.')
            db.execute("UPDATE files SET status='indexed',error=NULL,updated=? WHERE source=? AND path=?", (time.time(), sid, rel))
        except Exception:
            remove(identifier)
            errors += 1
            db.execute("UPDATE files SET status='error',error=?,updated=? WHERE source=? AND path=?",
                       ('Indexarea nu a reușit. Verifică documentul, modelele locale și serviciul Qdrant.', time.time(), sid, rel))
        db.commit()
    for rel, old in previous.items():
        if rel not in files and old['status'] != 'removed':
            remove(old['doc_id'])
            db.execute("UPDATE files SET status='removed',updated=? WHERE source=? AND path=?", (now, sid, rel))
    db.execute('UPDATE sources SET status=?,checked=?,error=NULL WHERE id=?', ('attention' if errors else 'pending' if pending else 'ready', now, sid))
    db.commit()


def convert(path, identifier, digest):
    from app.ingest.pdf import Chunk, DocMeta, chunk_document, convert_pdf, context_header
    from app.rag.index import BgeM3, index_chunks, qdrant_client
    meta = DocMeta(identifier, 'necunoscut', '', 'Document din folder de lucru', digest)
    if path.suffix.lower() in {'.txt', '.md', '.csv'}:
        text = path.read_text(encoding='utf-8-sig')
        chunks = [Chunk(identifier, i, 'text', 1, 1, None, context_header(meta, 1, 1) + '\n' + text[n:n+1500])
                  for i, n in enumerate(range(0, len(text), 1500))]
    else:
        chunks = chunk_document(convert_pdf(path, ocr=True), meta)
    if not chunks:
        raise ValueError('Document fără text utilizabil.')
    if content_digest(path) != digest:
        raise ValueError('Document modificat.')
    client = qdrant_client()
    try:
        index_chunks(client, BgeM3(), chunks, meta)
    finally:
        client.close()


def heartbeat():
    while True:
        db = connect()
        try:
            db.execute('INSERT OR REPLACE INTO worker VALUES(1,?)', (time.time(),))
            db.commit()
        finally:
            db.close()
        time.sleep(15)


def main():
    threading.Thread(target=heartbeat, daemon=True).start()
    while True:
        db = connect()
        try:
            for source in db.execute('SELECT * FROM sources').fetchall():
                try:
                    scan_source(db, source)
                except Exception:
                    # Unavailable sources are excluded, never silently served as current.
                    for row in db.execute("SELECT doc_id FROM files WHERE source=? AND status!='removed'", (source['id'],)).fetchall():
                        try:
                            remove_document(row['doc_id'])
                        except Exception:
                            pass
                    db.execute("UPDATE files SET status='error',error='Sursa nu este disponibilă.' WHERE source=? AND status!='removed'", (source['id'],))
                    db.execute("UPDATE sources SET status='error',checked=?,error=? WHERE id=?", (time.time(), 'Sursa nu este disponibilă sau indexarea este întreruptă. Verifică montarea folderului și serviciile.', source['id']))
                    db.commit()
        finally:
            db.close()
        time.sleep(30)


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--file':
        convert(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        main()
