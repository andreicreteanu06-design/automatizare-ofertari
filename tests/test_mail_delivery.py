import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_gateway import mail
from research_gateway.egress_guard import EgressGuard

OWNER = 'a' * 64


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv('MAIL_SERVICE_KEY', 'test-internal-service-key-' * 2)
    monkeypatch.setenv('MAIL_TOKEN_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('MAIL_DB_PATH', str(tmp_path / 'mail.sqlite3'))
    monkeypatch.setenv('MAIL_PUBLIC_URL', 'http://127.0.0.1:8080')
    for prefix in ('GOOGLE', 'MICROSOFT'):
        monkeypatch.setenv(prefix + '_CLIENT_ID', 'test-client')
        monkeypatch.setenv(prefix + '_CLIENT_SECRET', 'synthetic-secret')
    app = FastAPI()
    app.include_router(mail.router(EgressGuard(['confidentialproject'])))
    client = TestClient(app, headers={'X-Mail-Service-Key': 'test-internal-service-key-' * 2})
    return client


def account(provider='google', **extra):
    return dict(owner=OWNER, provider=provider, **extra)


def seed(provider='google', expires=None):
    store = mail.Store()
    store.save(OWNER, provider, dict(email='sender@example.com', access_token='synthetic-access', refresh_token='synthetic-refresh', expires_at=expires or time.time() + 3600))
    store.db.close()


def transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(mail.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))


def message(provider='google', **extra):
    return account(provider, request_id=str(uuid4()), to='buyer@example.com', subject='Cerere P1', body='Bună ziua, doresc 2 bucăți.', confirmed=True, **extra)


def test_internal_auth_and_configuration(setup, monkeypatch):
    assert setup.post('/mail/status', json=account(), headers={'X-Mail-Service-Key': 'wrong'}).status_code == 403
    monkeypatch.delenv('GOOGLE_CLIENT_SECRET')
    assert setup.post('/mail/status', json=account()).json()['configured'] is False


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_oauth_pkce_binding_replay_and_encrypted_storage(setup, monkeypatch, provider):
    query = parse_qs(urlsplit(setup.post('/mail/connect', json=account(provider)).json()['url']).query)
    assert 'client_secret' not in query
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == 'POST':
            fields = parse_qs(request.content.decode())
            challenge = base64.urlsafe_b64encode(hashlib.sha256(fields['code_verifier'][0].encode()).digest()).decode().rstrip('=')
            assert query['code_challenge'] == [challenge]
            return httpx.Response(200, json={'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh', 'expires_in': 3600})
        return httpx.Response(200, json={'email': 'sender@example.com', 'email_verified': True, 'mail': 'sender@example.com'})

    transport(monkeypatch, handler)
    callback = account(provider, state=query['state'][0], code='synthetic-code')
    assert setup.post('/mail/callback', json={**callback, 'owner': 'b' * 64}).status_code == 400
    assert not calls
    assert setup.post('/mail/callback', json=callback).status_code == 200
    assert setup.post('/mail/callback', json=callback).status_code == 400
    status = setup.post('/mail/status', json=account(provider)).json()
    assert status['email'] == 'sender@example.com' and 'access_token' not in status
    store = mail.Store()
    raw = store.db.execute('SELECT data FROM accounts').fetchone()[0]
    assert b'synthetic-access' not in raw and b'sender@example.com' not in raw
    store.db.close()


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_send_exact_message_and_idempotency(setup, monkeypatch, provider):
    seed(provider)
    calls = []
    def handler(request):
        import json
        from email import policy
        from email.parser import BytesParser
        calls.append(request)
        payload = json.loads(request.content)
        if provider == 'google':
            msg = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(payload['raw']))
            assert msg['To'] == 'buyer@example.com'
            assert msg['Subject'] == 'Cerere P1'
            assert '2 bucăți' in msg.get_content()
        else:
            assert payload['message']['body']['contentType'] == 'Text'
            assert payload['message']['toRecipients'][0]['emailAddress']['address'] == 'buyer@example.com'
        return httpx.Response(200 if provider == 'google' else 202, json={})
    transport(monkeypatch, handler)
    payload = message(provider)
    for _ in range(2):
        assert setup.post('/mail/send', json=payload).json() == {'status': 'accepted'}
    assert len(calls) == 1
    assert setup.post('/mail/send', json={**payload, 'body': 'alt mesaj'}).status_code == 409


def test_guard_blocks_recipient_subject_body_without_network(setup, monkeypatch):
    seed()
    transport(monkeypatch, lambda request: pytest.fail('Guard must block before network'))
    for field, value in [('to', 'confidentialproject@example.com'), ('subject', 'confidentialproject'), ('body', 'confidentialproject')]:
        assert setup.post('/mail/send', json={**message(), field: value}).status_code == 422
    assert setup.post('/mail/send', json={**message(), 'confirmed': False}).status_code == 422
    assert setup.post('/mail/send', json={**message(), 'subject': 'X\r\nBcc: x@example.com'}).status_code == 422


def test_ambiguous_send_never_retried(setup, monkeypatch):
    seed()
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('timeout')
    transport(monkeypatch, handler)
    payload = message()
    for _ in range(2):
        assert setup.post('/mail/send', json=payload).json()['status'] == 'unknown'
    assert len(calls) == 1


def test_refresh_and_disconnect(setup, monkeypatch):
    seed(expires=1)
    calls = []
    def handler(request):
        calls.append(request)
        if 'token' in str(request.url):
            return httpx.Response(200, json={'access_token': 'refreshed-access', 'expires_in': 3600})
        assert request.headers['Authorization'] == 'Bearer refreshed-access'
        return httpx.Response(200, json={})
    transport(monkeypatch, handler)
    assert setup.post('/mail/send', json=message()).json()['status'] == 'accepted'
    assert len(calls) == 2
    assert setup.post('/mail/disconnect', json=account()).status_code == 200
    assert setup.post('/mail/send', json=message()).status_code == 409


def test_backend_cookie_csrf_and_callback(monkeypatch):
    from app import mail_accounts
    monkeypatch.setenv('MAIL_SERVICE_KEY', 'x' * 40)
    monkeypatch.setenv('MAIL_PUBLIC_URL', 'http://testserver')
    calls = []
    async def fake(path, body):
        calls.append((path, body))
        return {'configured': True, 'connected': False, 'provider': body['provider']}
    monkeypatch.setattr(mail_accounts, 'gateway', fake)
    app = FastAPI()
    app.include_router(mail_accounts.router)
    with TestClient(app) as client:
        assert client.post('/emails/accounts/google/connect', json={}).status_code == 401
        r = client.get('/emails/accounts')
        assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=lax' in r.headers['set-cookie']
        assert client.post('/emails/accounts/google/connect', json={}, headers={'Origin': 'https://attacker.example'}).status_code == 403
        assert client.post('/emails/accounts/google/connect', data={}).status_code == 415
        assert client.post('/emails/accounts/google/connect', json={}).status_code == 200
        assert len(calls[-1][1]['owner']) == 64
        r = client.get('/emails/accounts/google/callback?state=abc&code=xyz', follow_redirects=False)
        assert r.headers['location'] == '/#email?oauth=connected'
        assert r.headers['referrer-policy'] == 'no-referrer'
