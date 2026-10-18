"""Organization login, separate from mail scopes. Only the gateway contacts IdPs."""
import os
import re
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer
from starlette.middleware.sessions import SessionMiddleware

COOKIE = 'ofertare_identity'


def install_login(app):
    if os.getenv('AUTH_ENABLED', 'false').lower() != 'true':
        return
    secret = os.getenv('AUTH_SESSION_SECRET', '')
    public = os.getenv('MAIL_PUBLIC_URL', '').rstrip('/')
    url = urlsplit(public)
    if len(secret) < 48 or url.path or url.query or url.fragment or url.username or not (
        url.scheme == 'https' or url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost')):
        raise RuntimeError('Configure AUTH_SESSION_SECRET and MAIL_PUBLIC_URL before enabling login')
    login = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    login.add_middleware(SessionMiddleware, secret_key=secret, session_cookie='ofertare_login_state',
                         max_age=600, same_site='lax', https_only=url.scheme == 'https')
    oauth = OAuth()
    domains = {v.strip().lower() for v in os.getenv('AUTH_GOOGLE_DOMAINS', '').split(',') if v.strip()}
    tenant = os.getenv('AUTH_MICROSOFT_TENANT', '')
    if domains and os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'):
        oauth.register('google', client_id=os.environ['GOOGLE_CLIENT_ID'], client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256', 'timeout': 15})
    if re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}', tenant) and os.getenv('MICROSOFT_CLIENT_ID') and os.getenv('MICROSOFT_CLIENT_SECRET'):
        oauth.register('microsoft', client_id=os.environ['MICROSOFT_CLIENT_ID'], client_secret=os.environ['MICROSOFT_CLIENT_SECRET'],
            server_metadata_url=f'https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256', 'timeout': 15})

    @login.get('/{provider}/login')
    async def start(provider: str, request: Request):
        if provider not in ('google', 'microsoft') or not oauth.create_client(provider):
            raise HTTPException(503, 'Autentificarea acestui furnizor nu este configurată.')
        request.session.clear()
        return await oauth.create_client(provider).authorize_redirect(request, f'{public}/api/auth/{provider}/callback')

    @login.get('/{provider}/callback')
    async def callback(provider: str, request: Request):
        try:
            if provider not in ('google', 'microsoft') or not oauth.create_client(provider):
                raise ValueError()
            token = await oauth.create_client(provider).authorize_access_token(request)
            claims = token['userinfo']  # Authlib validates signature, issuer, audience, expiry and nonce.
            if provider == 'google':
                domain = str(claims.get('hd', '')).lower()
                if not claims.get('email_verified') or domain not in domains:
                    raise ValueError()
                org = domain
            else:
                if str(claims.get('tid', '')).lower() != tenant.lower():
                    raise ValueError()
                org = tenant.lower()
            if not claims.get('sub'):
                raise ValueError()
            identity = {'provider': provider, 'sub': claims['sub'], 'org': org,
                        'email': claims.get('email') or claims.get('preferred_username') or '',
                        'name': claims.get('name') or 'Utilizator'}
            request.session.clear()
            response = RedirectResponse('/#chat', status_code=303)
            response.set_cookie(COOKIE, URLSafeTimedSerializer(secret, salt='ofertare-login-v1').dumps(identity),
                max_age=28800, httponly=True, secure=url.scheme == 'https', samesite='lax', path='/')
        except Exception:
            request.session.clear()
            response = RedirectResponse('/?login=failed#chat', status_code=303)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    app.mount('/auth', login)
