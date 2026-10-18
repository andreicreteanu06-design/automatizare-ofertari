"""Offline Docker volume backup; restore only into NEW volumes and an empty folder.

Run from the project root. Destination must be an encrypted, access-controlled disk.
No container is removed, no existing volume is overwritten, no mail is sent.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'postgres:17-alpine'
VOLUMES = {'postgres': 'pgdata', 'qdrant': 'qdrant', 'research-gateway': 'maildata'}
LOCAL = ('.env', 'config', 'secrets', 'data/inbox', 'data/source-uploads', 'data/source-state',
         'data/drive-mirror', 'data/drive-config', 'data/mail-quarantine', 'data/client-files')


def run(*args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        # Never echo command output: compose errors can include interpolated secrets.
        raise RuntimeError(f'Comanda {args[0]} a eșuat (cod {result.returncode}).')
    return result.stdout.strip()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fresh_directory(path):
    path = path.resolve()
    if path.exists():
        raise ValueError('Directorul destinație trebuie să fie nou.')
    if path.is_relative_to(ROOT) or any('onedrive' in p.lower() or 'dropbox' in p.lower() for p in path.parts):
        raise ValueError('Destinația trebuie să fie în afara proiectului și a folderelor cloud.')
    path.mkdir(parents=True, mode=0o700)
    return path


def archive_filter(info):
    if info.issym() or info.islnk() or not (info.isfile() or info.isdir()):
        raise ValueError('Backup oprit: legăturile și fișierele speciale necesită verificare manuală.')
    return info


def backup(destination):
    run('docker', 'info', '--format', '{{.ServerVersion}}')
    run('docker', 'image', 'inspect', IMAGE)
    mounts = {}
    images = {}
    for service, label in VOLUMES.items():
        cid = run('docker', 'compose', 'ps', '-aq', service)
        if not cid:
            raise ValueError(f'Serviciul {service} nu este creat.')
        info = json.loads(run('docker', 'inspect', cid))[0]
        images[service] = {'id': info.get('Image'), 'reference': info.get('Config', {}).get('Image')}
        targets = [m for m in info['Mounts'] if m['Type'] == 'volume']
        if len(targets) != 1:
            raise ValueError(f'Volumul {service} trebuie verificat manual.')
        mounts[label] = targets[0]['Name']
    running = run('docker', 'compose', 'ps', '--services', '--status', 'running').splitlines()
    destination = fresh_directory(destination)
    try:
        if running:
            run('docker', 'compose', 'stop', '--timeout', '120', *running)
        # Restart policies must not leave writers active during the physical snapshot.
        if run('docker', 'compose', 'ps', '--services', '--status', 'running'):
            raise RuntimeError('Containere încă active; backup anulat.')
        for label, volume in mounts.items():
            run('docker', 'run', '--rm', '--pull=never', '--network=none',
                '--mount', f'type=volume,src={volume},dst=/source,readonly',
                '--mount', f'type=bind,src={destination},dst=/backup', IMAGE,
                'tar', '-czf', f'/backup/{label}.tar.gz', '-C', '/source', '.')
        with tarfile.open(destination / 'local.tar.gz', 'w:gz') as archive:
            for name in LOCAL:
                path = ROOT / name
                if path.exists():
                    archive.add(path, arcname=name, filter=archive_filter)
        manifest = {'version': 1, 'created': datetime.now(timezone.utc).isoformat(), 'images': images,
                    'files': {p.name: digest(p) for p in destination.glob('*.tar.gz')},
                    'note': 'Modelele și directoarele CLIENT_DOCUMENTS_PATH externe nu sunt incluse. Copiază-le separat.'}
        (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        verify(destination)
    finally:
        if running:
            run('docker', 'compose', 'start', *running)


def verify(source):
    manifest = json.loads((source / 'manifest.json').read_text('utf-8'))
    expected = {'pgdata.tar.gz', 'qdrant.tar.gz', 'maildata.tar.gz', 'local.tar.gz'}
    if manifest.get('version') != 1 or set(manifest.get('files', {})) != expected:
        raise ValueError('Manifest invalid.')
    for name, checksum in manifest['files'].items():
        if digest(source / name) != checksum:
            raise ValueError('Backup corupt; restaurarea a fost refuzată.')
    return manifest


def restore(source, destination, prefix):
    verify(source)
    if not re.fullmatch(r'[a-z][a-z0-9_-]{2,40}', prefix):
        raise ValueError('Prefix invalid pentru volumele noi.')
    existing = run('docker', 'volume', 'ls', '--format', '{{.Name}}').splitlines()
    names = {label: f'{prefix}_{label}' for label in VOLUMES.values()}
    if any(name in existing for name in names.values()):
        raise ValueError('Volume existente: alege un prefix nou. Nimic nu a fost suprascris.')
    run('docker', 'image', 'inspect', IMAGE)
    for label in names:
        with tarfile.open(source / f'{label}.tar.gz', 'r:gz') as archive:
            for member in archive:
                # Physical snapshots with tablespace symlinks require a dedicated restore procedure.
                archive_filter(member)
                if member.name.startswith('/') or '..' in member.name.split('/'):
                    raise ValueError('Cale nesigură în arhivă.')
    destination = fresh_directory(destination)
    # Python data filter rejects archive traversal and dangerous link targets.
    with tarfile.open(source / 'local.tar.gz', 'r:gz') as archive:
        archive.extractall(destination, filter='data')
    for label, name in names.items():
        run('docker', 'volume', 'create', name)
        run('docker', 'run', '--rm', '--pull=never', '--network=none',
            '--mount', f'type=volume,src={name},dst=/target',
            '--mount', f'type=bind,src={source.resolve()},dst=/backup,readonly', IMAGE,
            'tar', '-xzf', f'/backup/{label}.tar.gz', '-C', '/target')
    override = {'volumes': {label: {'external': True, 'name': name} for label, name in names.items()}}
    (destination / 'restore-volumes.json').write_text(json.dumps(override, indent=2), 'utf-8')
    print('Restaurat în volume noi. Nu a fost pornit niciun serviciu. Verifică configurația înainte de utilizare.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'verify', 'restore'])
    parser.add_argument('path', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--prefix')
    args = parser.parse_args()
    try:
        if args.action == 'backup':
            backup(args.path)
        elif args.action == 'verify':
            verify(args.path)
            print('Integritatea arhivelor este validă; acesta nu este un test funcțional de restaurare.')
        else:
            if not args.destination or not args.prefix:
                parser.error('restore necesită --destination și --prefix')
            restore(args.path, args.destination, args.prefix)
    except Exception as exc:
        print(f'Operația nu a fost finalizată: {type(exc).__name__}. Verifică mediul și documentația BACKEND_OPERATIONS.md.')
        raise SystemExit(1)
