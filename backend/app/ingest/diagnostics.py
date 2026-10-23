"""Local, secret-free indexing checks. --retry queues errors, never deleted files."""
import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess

from app.sources import connect


def check_runtime():
    results = []
    def record(component, action):
        try:
            detail = action()
            results.append({'component': component, 'ok': True, 'detail': detail})
        except Exception as exc:
            # Do not print exception strings: network errors may contain secrets.
            result = {'component': component, 'ok': False, 'error_type': type(exc).__name__}
            if isinstance(exc, ModuleNotFoundError) and exc.name and re.fullmatch(r'[\w.]+', exc.name):
                result['missing_module'] = exc.name
            results.append(result)
    for name, module in [('docling', 'docling.document_converter'), ('FlagEmbedding', 'FlagEmbedding'), ('qdrant-client', 'qdrant_client')]:
        def imported(name=name, module=module):
            importlib.import_module(module)
            return importlib.metadata.version(name)
        record(name, imported)
    def ocr():
        process = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True, timeout=15, check=True)
        langs = set(process.stdout.splitlines())
        if not {'ron', 'eng'} <= langs:
            raise ValueError('languages')
        return 'ron + eng'
    record('Tesseract', ocr)
    def docling_models():
        folder = Path(os.getenv('DOCLING_ARTIFACTS_PATH', '/models/docling'))
        count = sum(1 for p in folder.rglob('*') if p.is_file() and p.suffix in ('.pt', '.bin', '.safetensors'))
        if not count:
            raise FileNotFoundError('models')
        return f'{count} fișiere de greutăți; compatibilitatea se verifică la conversie'
    record('Modele Docling', docling_models)
    def bge_models():
        from app.rag.model_cache import cached_bge_model
        cached_bge_model(os.getenv('BGE_M3_MODEL', 'BAAI/bge-m3'))
        return 'fișiere locale de inferență prezente; exporturile ONNX nu sunt necesare'
    record('Modele BGE-M3', bge_models)
    def qdrant():
        from app.rag.index import qdrant_client
        client = qdrant_client()
        try:
            client.get_collections()
        finally:
            client.close()
        return 'conectat'
    record('Qdrant', qdrant)
    return results


def retry_errors(db):
    db.execute('BEGIN IMMEDIATE')
    affected = db.execute("""SELECT DISTINCT source FROM files WHERE status='error'
        AND source NOT IN (SELECT source FROM source_removals)
        AND NOT EXISTS (SELECT 1 FROM file_removals r WHERE r.source=files.source AND r.path=files.path)""").fetchall()
    queued = 0
    for row in affected:
        queued += db.execute("""UPDATE files SET status='pending',updated=0,error=NULL WHERE source=? AND status='error'
            AND NOT EXISTS (SELECT 1 FROM file_removals r WHERE r.source=files.source AND r.path=files.path)""", (row['source'],)).rowcount
        db.execute("UPDATE sources SET status='pending',error=NULL WHERE id=?", (row['source'],))
    db.commit()
    return queued


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry', action='store_true')
    args = parser.parse_args()
    results = check_runtime()
    for result in results:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    if not all(r['ok'] for r in results):
        print('Nu au fost repuse documente în coadă. Remediază componentele marcate ok=false conform INDEXING.md.')
        return 1
    db = connect()
    try:
        if args.retry:
            print(json.dumps({'queued': retry_errors(db)}), flush=True)
        print(json.dumps({'file_states': dict(db.execute('SELECT status,count(*) FROM files GROUP BY status').fetchall())}), flush=True)
    finally:
        db.close()
    print('Preverificare încheiată. Așteaptă starea Indexat; acest control nu certifică rezultatele OCR.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
