"""Read-only local deployment checks. Never prints secret values."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def check():
    results = []
    def record(label, ok):
        results.append(ok)
        print(('OK  ' if ok else 'LIPSĂ  ') + label)
    record('Proiect în afara OneDrive', not any('onedrive' in p.lower() for p in ROOT.parts))
    for name in ('.env', 'config/denylist.yaml'):
        record(name, (ROOT / name).is_file())
    # Let Compose validate interpolation itself; suppress its output (may contain secrets).
    for label, command in [('Docker funcțional', ['docker','info']),
        ('Configurație Compose validă', ['docker','compose','--profile','ui','config','--quiet'])]:
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=30)
            record(label, result.returncode == 0)
        except (OSError, subprocess.TimeoutExpired):
            record(label, False)
    print('Acest control nu validează modelele, OAuth, exactitatea RAG sau importul Saga.')
    return all(results)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(0 if check() else 1)
