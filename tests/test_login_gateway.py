import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from research_gateway.login import install_login


@pytest.fixture
def login(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED','true')
    monkeypatch.setenv('AUTH_SESSION_SECRET','synthetic-login-secret-' * 4)
    monkeypatch.setenv('MAIL_PUBLIC_URL','http://127.0.0.1:8080')
    monkeypatch.setenv('AUTH_GOOGLE_DOMAINS','example.test')
    monkeypatch.setenv('GOOGLE_CLIENT_ID','synthetic')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET','synthetic')
    app = FastAPI()
    install_login(app)
    return TestClient(app)


def test_oauth_missing_state_fails_closed(login):
    # Authlib rejects absent state before any token exchange.
    response = login.get('/auth/google/callback?code=synthetic', follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/?login=failed#chat'
    assert 'ofertare_identity=' not in response.headers.get('set-cookie', '')


@pytest.mark.parametrize('domain,verified,success', [('example.test',True,True), ('evil.test',True,False), ('example.test',False,False)])
def test_verified_claims_organization_policy(login, monkeypatch, domain, verified, success):
    from authlib.integrations.starlette_client.apps import StarletteOAuth2App
    async def verified_token(self, request):
        return {'userinfo': {'sub':'synthetic-user','hd':domain,'email_verified':verified,'email':'employee@example.test'},
                'access_token':'must-not-enter-cookie'}
    monkeypatch.setattr(StarletteOAuth2App, 'authorize_access_token', verified_token)
    response = login.get('/auth/google/callback', follow_redirects=False)
    assert response.headers['location'] == ('/#chat' if success else '/?login=failed#chat')
    if success:
        value = response.cookies['ofertare_identity']
        user = URLSafeTimedSerializer('synthetic-login-secret-' * 4, salt='ofertare-login-v1').loads(value)
        assert user['sub'] == 'synthetic-user'
        assert 'access_token' not in user
    else:
        assert 'ofertare_identity' not in response.cookies


def test_enabling_with_missing_key_refuses_startup(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED','true')
    monkeypatch.setenv('AUTH_SESSION_SECRET','')
    with pytest.raises(RuntimeError):
        install_login(FastAPI())
