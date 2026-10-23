"""Same-origin mail facade; tokens remain in the egress gateway."""
import hashlib
import os
import secrets
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix='/emails')
COOKIE = 'ofertare_mail'
Provider = Literal['google', 'microsoft']


def owner(request):
    from app.auth import account_owner
    user = account_owner(request)
    if user:
        return user
    token = request.cookies.get(COOKIE, '')
    if not 40 <= len(token) <= 100:
        raise HTTPException(401, 'Reîncarcă pagina pentru inițializarea contului.')
    return hashlib.sha256(token.encode()).hexdigest()


def same_origin(request):
    # JSON-only mutations cannot be submitted by a cross-site HTML form.
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'Este necesar application/json.')
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != os.getenv('MAIL_PUBLIC_URL', '').rstrip('/'):
        raise HTTPException(403, 'Origine neautorizată. Verifică MAIL_PUBLIC_URL.')


async def gateway(path, data):
    key = os.getenv('MAIL_SERVICE_KEY', '')
    if len(key) < 32:
        raise HTTPException(503, 'Conectarea e-mail necesită configurarea OAuth în .env. Consultă EMAIL_CONNECT.md.')
    try:
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            r = await client.post(os.environ['RESEARCH_GATEWAY_URL'].rstrip('/') + '/mail/' + path, json=data, headers={'X-Mail-Service-Key': key})
            if r.status_code >= 500:
                raise HTTPException(503, 'Serviciul e-mail nu este disponibil sau configurat. Consultă EMAIL_CONNECT.md.')
            if not r.is_success:
                raise HTTPException(r.status_code, r.json().get('detail', 'Cerere e-mail refuzată.'))
            return r.json()
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(503, 'Serviciul e-mail nu răspunde. Pentru trimitere, verifică folderul Trimise înainte de o nouă încercare.') from None


@router.get('/accounts')
async def accounts(request: Request, response: Response):
    token = request.cookies.get(COOKIE, '')
    if not 40 <= len(token) <= 100:
        token = secrets.token_urlsafe(48)
    response.set_cookie(COOKIE, token, httponly=True, samesite='lax', secure=os.getenv('COOKIE_SECURE', 'false').lower() == 'true', max_age=365 * 86400, path='/')
    response.headers['Cache-Control'] = 'no-store'
    from app.auth import account_owner
    identity = account_owner(request) or hashlib.sha256(token.encode()).hexdigest()
    if len(os.getenv('MAIL_SERVICE_KEY', '')) < 32:
        return [{'provider': p, 'configured': False, 'connected': False,
                 'setup': {'missing_settings': ['MAIL_SERVICE_KEY'] if not os.getenv('MAIL_SERVICE_KEY') else [],
                           'invalid_settings': ['MAIL_SERVICE_KEY'] if os.getenv('MAIL_SERVICE_KEY') else [],
                           'redirect_uri': None}} for p in ('google', 'microsoft')]
    return [await gateway('status', {'owner': identity, 'provider': p}) for p in ('google', 'microsoft')]


@router.post('/accounts/{provider}/connect')
async def connect(provider: Provider, request: Request):
    same_origin(request)
    return await gateway('connect', {'owner': owner(request), 'provider': provider})


@router.post('/accounts/{provider}/disconnect')
async def disconnect(provider: Provider, request: Request):
    same_origin(request)
    return await gateway('disconnect', {'owner': owner(request), 'provider': provider})


@router.get('/accounts/{provider}/callback')
async def callback(provider: Provider, request: Request, state: str = '', code: str = '', error: str = ''):
    outcome = 'error'
    if not error and code and state:
        try:
            await gateway('callback', {'owner': owner(request), 'provider': provider, 'state': state, 'code': code})
            outcome = 'connected'
        except HTTPException:
            pass
    # A relative redirect avoids reflecting any caller-controlled URL or provider error.
    return RedirectResponse('/#email?oauth=' + outcome, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


class SendIn(BaseModel):
    provider: Provider
    request_id: str = Field(max_length=36)
    to: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=50000)
    logo_base64: str | None = Field(default=None, max_length=700000)
    confirmed: Literal[True]


@router.post('/send')
async def send(body: SendIn, request: Request):
    same_origin(request)
    return await gateway('send', {**body.model_dump(), 'owner': owner(request)})
