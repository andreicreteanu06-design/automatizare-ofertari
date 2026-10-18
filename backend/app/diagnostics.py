"""Bounded dependency probes. No generation, external search or secret disclosure."""
import asyncio
import os
import sqlite3
import time
from pathlib import Path

import httpx
import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


async def database():
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL'], connect_timeout=3,
                                                    options='-c statement_timeout=2000') as conn:
        await conn.execute('SELECT 1')


def worker():
    path = Path(os.getenv('SOURCE_STATE_ROOT', '/data/source-state')) / 'sources.sqlite3'
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1) as conn:
        row = conn.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
    if not row or not 0 <= time.time() - row[0] < 120:
        raise ValueError('stale')


async def probe(name, label, action, required=True):
    try:
        async with asyncio.timeout(5):
            await action()
        status = 'ok'
    except Exception:
        status = 'unavailable'
    return dict(id=name, label=label, status=status, required=required)


async def checks():
    async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False) as client:
        async def get(env, suffix, headers=None):
            response = await client.get(os.environ[env].rstrip('/') + suffix, headers=headers)
            response.raise_for_status()
        async def model():
            response = await client.get(os.environ['COLIBRI_URL'].rstrip('/') + '/models')
            response.raise_for_status()
            if not response.json().get('data'):
                raise ValueError('No advertised model')
        return await asyncio.gather(
            probe('postgres', 'Baza de date și conversații', database),
            probe('qdrant', 'Indexul documentelor', lambda: get('QDRANT_URL', '/collections',
                  {'api-key': os.getenv('QDRANT_API_KEY', '')})),
            probe('colibri', 'Modelul pentru răspunsuri', model),
            probe('gateway', 'Serviciul de curs valutar, web și e-mail',
                  lambda: get('RESEARCH_GATEWAY_URL', '/health'), False),
            probe('source_worker', 'Procesarea automată a documentelor',
                  lambda: asyncio.to_thread(worker), False),
        )


@router.get('/diagnostics')
async def diagnostics():
    services = await checks()
    return JSONResponse({'ok': all(s['status'] == 'ok' for s in services), 'services': services,
        'note': 'Conectivitate verificată; generarea AI, OCR și integrările externe necesită teste separate.'},
        headers={'Cache-Control': 'no-store'})


@router.get('/ready')
async def ready():
    services = await checks()
    ok = all(s['status'] == 'ok' for s in services if s['required'])
    return JSONResponse({'ok': ok}, status_code=200 if ok else 503,
                        headers={'Cache-Control': 'no-store'})
