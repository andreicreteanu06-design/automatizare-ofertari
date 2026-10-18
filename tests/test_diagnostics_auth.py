import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from app.main import app
from app import diagnostics, auth


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    monkeypatch.setenv('AUTH_SESSION_SECRET', 'synthetic-test-secret-' * 4)
    monkeypatch.setenv('AUTH_GOOGLE_DOMAINS', 'example.test')
    monkeypatch.setenv('AUTH_MICROSOFT_TENANT', '12345678-1234-1234-1234-123456789012')
    monkeypatch.setenv('MAIL_PUBLIC_URL', 'http://testserver')
    return TestClient(app)


def cookie(provider='google', org='example.test', sub='123'):
    return URLSafeTimedSerializer('synthetic-test-secret-' * 4, salt='ofertare-login-v1').dumps(
        dict(provider=provider, org=org, sub=sub, email='user@example.test'))


def test_protected_endpoints_and_public_liveness(secured):
    assert secured.get('/health').status_code == 200
    for path in ['/sources', '/conversations', '/diagnostics', '/docs', '/openapi.json']:
        assert secured.get(path).status_code == 401
    assert secured.get('/auth/session').json()['user'] is None


@pytest.mark.parametrize('value', ['corrupted', cookie(org='attacker.test'), cookie(provider='unknown')])
def test_rejects_tampering_and_unapproved_organizations(secured, value):
    secured.cookies.set(auth.COOKIE, value)
    assert secured.get('/diagnostics').status_code == 401


@pytest.mark.parametrize('provider,org', [('google', 'example.test'), ('microsoft','12345678-1234-1234-1234-123456789012')])
def test_login_session_and_csrf(secured, provider, org):
    secured.cookies.set(auth.COOKIE, cookie(provider, org))
    assert secured.get('/auth/session').json()['user']['provider'] == provider
    assert secured.post('/conversations', json={}).status_code == 403
    assert secured.post('/auth/logout', headers={'Origin': 'https://evil.test'}).status_code == 403
    response = secured.post('/auth/logout', headers={'Origin': 'http://testserver'})
    assert response.status_code == 200
    assert 'Max-Age=0' in response.headers['set-cookie']


def test_diagnostics_optional_failure_vs_readiness(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'false')
    async def results():
        return [dict(id='postgres', required=True, status='ok'),
                dict(id='gateway', required=False, status='unavailable')]
    monkeypatch.setattr(diagnostics, 'checks', results)
    client = TestClient(app)
    assert client.get('/diagnostics').json()['ok'] is False
    assert client.get('/ready').status_code == 200
    async def failed():
        return [dict(id='postgres', required=True, status='unavailable')]
    monkeypatch.setattr(diagnostics, 'checks', failed)
    assert client.get('/ready').status_code == 503


def test_probe_hides_secrets():
    async def fail():
        raise ValueError('password=do-not-expose')
    result = asyncio.run(diagnostics.probe('db', 'Database', fail))
    assert result['status'] == 'unavailable'
    assert 'password' not in json.dumps(result)


def test_worker_missing_and_stale(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv('SOURCE_STATE_ROOT', str(tmp_path))
    with pytest.raises(sqlite3.OperationalError):
        diagnostics.worker()
    with sqlite3.connect(tmp_path / 'sources.sqlite3') as db:
        db.execute('CREATE TABLE worker (id INTEGER PRIMARY KEY, heartbeat REAL)')
        db.execute('INSERT INTO worker VALUES(1, ?)', (time.time() - 300,))
    with pytest.raises(ValueError):
        diagnostics.worker()


def test_expired_session_rejected(secured, monkeypatch):
    import itsdangerous.timed
    value = cookie()
    now = time.time()
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, 'get_timestamp', lambda self: int(now + 30000))
    secured.cookies.set(auth.COOKIE, value)
    assert secured.get('/diagnostics').status_code == 401


def test_account_memory_survives_browser_cookie_and_is_isolated(secured):
    from app.memory import get_store
    from tests.test_memory_api import Store
    store = Store()
    app.dependency_overrides[get_store] = lambda: store
    try:
        secured.cookies.set(auth.COOKIE, cookie(sub='first'))
        created = secured.post('/conversations', json={'project':'Test','title':'Private'},
                               headers={'Origin':'http://testserver'})
        assert created.status_code == 200
        cid = created.json()['id']
        secured.cookies.clear()
        secured.cookies.set(auth.COOKIE, cookie(sub='first'))
        assert secured.get('/conversations').json()[0]['id'] == cid
        secured.cookies.set(auth.COOKIE, cookie(sub='second'))
        assert secured.get('/conversations').json() == []
        assert secured.get('/conversations/' + cid).status_code == 404
    finally:
        app.dependency_overrides.pop(get_store, None)
