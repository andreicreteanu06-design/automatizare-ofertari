"""Verify gateway-issued identities locally; no IdP network access in backend."""
import hashlib
import json
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

router = APIRouter(prefix='/auth')
COOKIE = 'ofertare_identity'


def enabled():
    return os.getenv('AUTH_ENABLED', 'false').lower() == 'true'


def identity(request):
    if not enabled():
        return None
    secret = os.getenv('AUTH_SESSION_SECRET', '')
    if len(secret) < 48:
        raise HTTPException(503, 'Autentificarea necesită configurarea administratorului.')
    try:
        raw = request.cookies.get(COOKIE, '')
        if len(raw) > 4096:
            raise ValueError()
        value = URLSafeTimedSerializer(secret, salt='ofertare-login-v1').loads(raw, max_age=28800)
        if not isinstance(value, dict) or not isinstance(value.get('sub'), str) or not value['sub']:
            raise ValueError()
        if value['provider'] == 'google':
            allowed = {d.strip().lower() for d in os.getenv('AUTH_GOOGLE_DOMAINS', '').split(',') if d.strip()}
            if value['org'] not in allowed:
                raise ValueError()
        elif value['provider'] == 'microsoft':
            if not value.get('org') or value['org'] != os.getenv('AUTH_MICROSOFT_TENANT', '').lower():
                raise ValueError()
        else:
            raise ValueError()
        return value
    except (BadSignature, ValueError, KeyError, TypeError):
        raise HTTPException(401, 'Conectează-te cu contul organizației.') from None


def account_owner(request):
    user = identity(request)
    if user:
        return hashlib.sha256(json.dumps([user['provider'], user['org'], user['sub']]).encode()).hexdigest()


async def protect(request, call_next):
    if enabled() and request.url.path not in ('/health', '/ready') and not request.url.path.startswith('/auth/'):
        try:
            identity(request)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                public = os.getenv('MAIL_PUBLIC_URL', '').rstrip('/')
                if request.headers.get('origin', '').rstrip('/') != public:
                    raise HTTPException(403, 'Origine neautorizată.')
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
    return await call_next(request)


@router.get('/session')
async def session(request: Request):
    user = None
    try:
        user = identity(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    return JSONResponse({'enabled': enabled(), 'user': user}, headers={'Cache-Control': 'no-store'})


@router.post('/logout')
async def logout(request: Request):
    if request.headers.get('origin', '').rstrip('/') != os.getenv('MAIL_PUBLIC_URL', '').rstrip('/'):
        raise HTTPException(403, 'Origine neautorizată.')
    response = JSONResponse({'ok': True}, headers={'Cache-Control': 'no-store'})
    for cookie in (COOKIE, 'ofertare_login_state', 'ofertare_workspace', 'ofertare_mail'):
        response.delete_cookie(cookie, path='/')
    return response


@router.get('/{provider}/{action}')
async def relay(provider: str, action: str, request: Request):
    if not enabled() or provider not in ('google', 'microsoft') or action not in ('login', 'callback'):
        raise HTTPException(404)
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False) as client:
            upstream = await client.get(os.environ['RESEARCH_GATEWAY_URL'].rstrip('/') + f'/auth/{provider}/{action}',
                params=request.query_params, headers={'Cookie': request.headers.get('cookie', '')})
        response = Response(upstream.content, status_code=upstream.status_code,
                            media_type=upstream.headers.get('content-type'))
        for key in ('location', 'set-cookie'):
            for value in upstream.headers.get_list(key):
                response.headers.append(key, value)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response
    except (httpx.HTTPError, KeyError):
        raise HTTPException(503, 'Serviciul de autentificare nu este disponibil.') from None
