"""Read-only Google Drive mirror via pinned gws CLI, on egress network only."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from research_gateway.egress_guard import load

ID = re.compile(r'^[A-Za-z0-9_-]{10,200}$')
MAX_BYTES = int(os.getenv('SOURCE_MAX_FILE_MB', '250')) * 1024 * 1024
MAX_FILES = int(os.getenv('SOURCE_MAX_FILES', '50000'))
if not 1 <= MAX_BYTES // (1024 * 1024) <= 1024 or not 1 <= MAX_FILES <= 1000000:
    raise ValueError('Limite Drive invalide.')
EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.txt', '.md', '.csv'}
EXPORTS = {'application/vnd.google-apps.document': ('application/pdf', '.pdf'),
           'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx')}


def run_gws(method, params, guard, output=None):
    guard.check(params)
    args = ['gws', 'drive', 'files', method, '--params', json.dumps(params)]
    if output:
        args += ['--output', str(output)]
    result = subprocess.run(args, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Google Drive indisponibil; verifică autorizarea și permisiunile.')
    return {} if output else json.loads(result.stdout)


def inventory(folder, guard, call=run_gws):
    if not ID.fullmatch(folder):
        raise ValueError('Invalid folder ID')
    pending, seen, files = [folder], set(), []
    while pending:
        parent = pending.pop()
        if parent in seen:
            continue
        seen.add(parent)
        token = None
        tokens = set()
        while True:
            params = {'q': f"'{parent}' in parents and trashed = false", 'fields': 'nextPageToken,incompleteSearch,files(id,name,mimeType,size,modifiedTime,md5Checksum)', 'pageSize': 100,
                      'supportsAllDrives': True, 'includeItemsFromAllDrives': True}
            if token:
                params['pageToken'] = token
            data = call('list', params, guard)
            if data.get('incompleteSearch'):
                raise ValueError('Inventar Drive incomplet.')
            for item in data.get('files', []):
                if not ID.fullmatch(item['id']):
                    raise ValueError('Invalid file ID')
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    pending.append(item['id'])
                elif item['mimeType'] in EXPORTS or Path(item['name']).suffix.lower() in EXTENSIONS:
                    if item['mimeType'] == 'application/vnd.google-apps.shortcut':
                        continue
                    if int(item.get('size', 0)) > MAX_BYTES:
                        raise ValueError(f'Fișier Drive peste {MAX_BYTES // 1024 ** 2} MB.')
                    files.append(item)
                if len(files) + len(pending) + len(seen) > MAX_FILES:
                    raise ValueError(f'Maximum {MAX_FILES:,} intrări per folder Drive.')
            token = data.get('nextPageToken')
            if not token:
                break
            if token in tokens or len(tokens) >= MAX_FILES:
                raise ValueError('Paginare Drive incompletă.')
            tokens.add(token)
    return files


def atomic_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data), encoding='utf-8')
    tmp.replace(path)


def sync(config, mirror, guard, call=run_gws):
    if not re.fullmatch(r'[a-f0-9-]{36}', config['source_id']):
        raise ValueError('Invalid source ID')
    folder = mirror / config['source_id']
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / '.sync.json'
    old = json.loads(manifest.read_text()) if manifest.exists() else {}
    expected, changes, revisions = set(), [], {}
    try:
        for item in inventory(config['folder_id'], guard, call):
            export = EXPORTS.get(item['mimeType'])
            suffix = export[1] if export else Path(item['name']).suffix.lower()
            name = item['id'] + suffix
            expected.add(name)
            revision = item.get('md5Checksum') or item.get('modifiedTime')
            if not revision:
                raise ValueError('Missing revision')
            revisions[name] = revision
            target = folder / name
            if old.get('revisions', {}).get(name) == revision and target.is_file():
                continue
            tmp = folder / ('.' + name + '.part')
            params = {'fileId': item['id']}
            if export:
                params['mimeType'] = export[0]
            else:
                params.update(alt='media', supportsAllDrives=True)
            call('export' if export else 'get', params, guard, tmp)
            if not tmp.exists() or not 0 < tmp.stat().st_size <= MAX_BYTES:
                raise ValueError('Invalid download size')
            changes.append((tmp, target))
        atomic_json(manifest, {'status': 'syncing', 'checked': time.time()})
        for tmp, target in changes:
            tmp.replace(target)
        for target in folder.iterdir():
            # Only our own generated filenames may be removed, never client folders.
            if target.is_file() and not target.name.startswith('.') and target.name not in expected:
                target.unlink()
        atomic_json(manifest, {'status': 'ready', 'checked': time.time(), 'revisions': revisions})
    except Exception:
        atomic_json(manifest, {**old, 'status': 'error', 'checked': time.time()})
        raise
    finally:
        for temporary in folder.glob('.*.part'):
            temporary.unlink(missing_ok=True)


def main():
    guard = load()
    while True:
        for path in Path('/config/drive-sources').glob('*.json'):
            try:
                sync(json.loads(path.read_text()), Path('/mirror'), guard)
            except Exception:
                print('Sincronizare Drive nereușită; verifică autorizarea, limita sau Egress Guard.', flush=True)
        time.sleep(60)


if __name__ == '__main__':
    main()
