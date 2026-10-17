"""OAuth send-only adapters. Provider credentials never cross the internal API."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from research_gateway.egress_guard import EgressBlocked

Provider = Literal['google', 'microsoft']


class AccountIn(BaseModel):
    owner: str = Field(pattern=r'^[a-f0-9]{64}$')
    provider: Provider


class CallbackIn(AccountIn):
    state: str = Field(min_length=20, max_length=200)
    code: str = Field(min_length=1, max_length=8192)


class SendIn(AccountIn):
    request_id: UUID
    to: str = Field(max_length=254)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=50000)
    confirmed: Literal[True]

    @field_validator('to')
    @classmethod
    def address(cls, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}", value):
            raise ValueError('Introdu o singură adresă de e-mail validă.')
        return value

    @field_validator('subject')
    @classmethod
    def no_headers(cls, value):
        if '\r' in value or '\n' in value or not value.strip():
            raise ValueError('Subiect invalid.')
        return value


def config(provider):
    prefix = 'GOOGLE' if provider == 'google' else 'MICROSOFT'
    client_id, secret = (os.getenv(prefix + suffix, '') for suffix in ('_CLIENT_ID', '_CLIENT_SECRET'))
    public = os.getenv('MAIL_PUBLIC_URL', '').rstrip('/')
    p = urlsplit(public)
    if not client_id or not secret or not (p.scheme == 'https' or (p.scheme == 'http' and p.hostname in ('localhost', '127.0.0.1'))) or p.path or p.query or p.fragment or p.username:
        raise HTTPException(503, 'Administratorul trebuie să configureze OAuth și MAIL_PUBLIC_URL în .env.')
    if provider == 'google':
        auth, token = 'https://accounts.google.com/o/oauth2/v2/auth', 'https://oauth2.googleapis.com/token'
        scope = 'openid email https://www.googleapis.com/auth/gmail.send'
    else:
        tenant = os.getenv('MICROSOFT_TENANT', 'common')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+', tenant):
            raise HTTPException(503, 'MICROSOFT_TENANT invalid.')
        auth = f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize'
        token = f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
        scope = 'offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Send'
    return dict(client_id=client_id, client_secret=secret, redirect_uri=f'{public}/api/emails/accounts/{provider}/callback', scope=scope), auth, token


class Store:
    def __init__(self):
        try:
            self.cipher = Fernet(os.environ['MAIL_TOKEN_KEY'].encode())
        except (KeyError, ValueError):
            raise HTTPException(503, 'Configurează MAIL_TOKEN_KEY în .env.') from None
        path = Path(os.getenv('MAIL_DB_PATH', '/mail-data/mail.sqlite3'))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS accounts(owner TEXT, provider TEXT, data BLOB, PRIMARY KEY(owner,provider));
        CREATE TABLE IF NOT EXISTS pending(state TEXT PRIMARY KEY, owner TEXT, provider TEXT, expires REAL, data BLOB);
        CREATE TABLE IF NOT EXISTS sends(owner TEXT, id TEXT, digest TEXT, status TEXT, PRIMARY KEY(owner,id));
        ''')
        self.db.execute('DELETE FROM pending WHERE expires < ?', (time.time(),))
        self.db.commit()

    def seal(self, data):
        return self.cipher.encrypt(json.dumps(data).encode())

    def read(self, data):
        return json.loads(self.cipher.decrypt(data))

    def save(self, owner, provider, data):
        self.db.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?)', (owner, provider, self.seal(data)))
        self.db.commit()

    def account(self, owner, provider):
        row = self.db.execute('SELECT data FROM accounts WHERE owner=? AND provider=?', (owner, provider)).fetchone()
        if not row:
            raise HTTPException(409, 'Conectează contul de e-mail.')
        return self.read(row['data'])


def get_store():
    store = Store()
    try:
        yield store
    finally:
        store.db.close()


def authorize(x_mail_service_key: str = Header(default='')):
    expected = os.getenv('MAIL_SERVICE_KEY', '')
    if len(expected) < 32:
        raise HTTPException(503, 'Configurează MAIL_SERVICE_KEY în .env.')
    if not hmac.compare_digest(expected, x_mail_service_key):
        raise HTTPException(403, 'Acces refuzat.')


async def token_request(url, data):
    try:
        async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            result = response.json()
            if not result.get('access_token'):
                raise ValueError()
            return result
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Autorizarea furnizorului a eșuat. Reconectează contul.') from None


def router(guard):
    routes = APIRouter(prefix='/mail', dependencies=[Depends(authorize)])

    @routes.post('/status')
    def status(body: AccountIn):
        try:
            config(body.provider)
            store = Store()
        except HTTPException:
            return {'provider': body.provider, 'configured': False, 'connected': False}
        try:
            row = store.db.execute('SELECT data FROM accounts WHERE owner=? AND provider=?', (body.owner, body.provider)).fetchone()
            account = store.read(row['data']) if row else None
            return {'provider': body.provider, 'configured': True, 'connected': bool(account), 'email': account['email'] if account else None}
        finally:
            store.db.close()

    @routes.post('/connect')
    def connect(body: AccountIn, store=Depends(get_store)):
        cfg, auth, _ = config(body.provider)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        store.db.execute('INSERT INTO pending VALUES(?,?,?,?,?)', (state, body.owner, body.provider, time.time() + 600, store.seal(verifier)))
        store.db.commit()
        params = {k: v for k, v in cfg.items() if k != 'client_secret'}
        params.update(response_type='code', state=state, code_challenge_method='S256', code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='), prompt='consent')
        if body.provider == 'google':
            params['access_type'] = 'offline'
        return {'url': auth + '?' + urlencode(params)}

    @routes.post('/callback')
    async def callback(body: CallbackIn, store=Depends(get_store)):
        row = store.db.execute('DELETE FROM pending WHERE state=? AND owner=? AND provider=? AND expires>? RETURNING data', (body.state, body.owner, body.provider, time.time())).fetchone()
        store.db.commit()
        if not row:
            raise HTTPException(400, 'Conectare expirată sau deja folosită. Reia conectarea.')
        cfg, _, endpoint = config(body.provider)
        tokens = await token_request(endpoint, {**cfg, 'grant_type': 'authorization_code', 'code': body.code, 'code_verifier': store.read(row['data'])})
        url = 'https://openidconnect.googleapis.com/v1/userinfo' if body.provider == 'google' else 'https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName'
        try:
            async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
                result = await client.get(url, headers={'Authorization': 'Bearer ' + tokens['access_token']})
                result.raise_for_status()
                info = result.json()
                email = info.get('email') if body.provider == 'google' else info.get('mail') or info.get('userPrincipalName')
                if not email or (body.provider == 'google' and info.get('email_verified') is not True):
                    raise ValueError()
                email = SendIn.address(email)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Identitatea contului nu a putut fi verificată.') from None
        store.save(body.owner, body.provider, {**tokens, 'email': email, 'expires_at': time.time() + int(tokens.get('expires_in', 3600))})
        return {'ok': True}

    @routes.post('/disconnect')
    def disconnect(body: AccountIn, store=Depends(get_store)):
        store.db.execute('DELETE FROM accounts WHERE owner=? AND provider=?', (body.owner, body.provider))
        store.db.execute('DELETE FROM pending WHERE owner=? AND provider=?', (body.owner, body.provider))
        store.db.commit()
        return {'ok': True}

    @routes.post('/send')
    async def send(body: SendIn, store=Depends(get_store)):
        account = store.account(body.owner, body.provider)
        try:
            guard.check([account['email'], body.to, body.subject, body.body])
        except EgressBlocked as exc:
            raise HTTPException(422, {'error': 'Trimitere blocată de Egress Guard.', 'rules': exc.rules}) from None
        digest = hashlib.sha256(json.dumps([body.provider, account['email'], body.to, body.subject, body.body]).encode()).hexdigest()
        old = store.db.execute('SELECT digest,status FROM sends WHERE owner=? AND id=?', (body.owner, str(body.request_id))).fetchone()
        if old:
            if old['digest'] != digest:
                raise HTTPException(409, 'ID folosit pentru alt mesaj.')
            return {'status': old['status']}
        if account['expires_at'] < time.time() + 120:
            if not account.get('refresh_token'):
                raise HTTPException(409, 'Reconectează contul de e-mail.')
            cfg, _, endpoint = config(body.provider)
            refreshed = await token_request(endpoint, {**cfg, 'grant_type': 'refresh_token', 'refresh_token': account['refresh_token']})
            account.update(refreshed)
            account['expires_at'] = time.time() + int(refreshed.get('expires_in', 3600))
            store.save(body.owner, body.provider, account)
        # Reserve before outbound I/O, including concurrent requests and process crashes.
        try:
            store.db.execute('INSERT INTO sends VALUES(?,?,?,?)', (body.owner, str(body.request_id), digest, 'unknown'))
            store.db.commit()
        except sqlite3.IntegrityError:
            return {'status': 'unknown'}
        if body.provider == 'google':
            message = EmailMessage()
            message['From'], message['To'], message['Subject'] = account['email'], body.to, body.subject
            message.set_content(body.body)
            url = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
            payload = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        else:
            url = 'https://graph.microsoft.com/v1.0/me/sendMail'
            payload = {'message': {'subject': body.subject, 'body': {'contentType': 'Text', 'content': body.body}, 'toRecipients': [{'emailAddress': {'address': body.to}}]}, 'saveToSentItems': True}
        status = 'unknown'
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                result = await client.post(url, headers={'Authorization': 'Bearer ' + account['access_token']}, json=payload)
                if result.status_code in (200, 202):
                    status = 'accepted'
                elif 400 <= result.status_code < 500:
                    status = 'rejected'
        except httpx.HTTPError:
            pass  # Never retry a send automatically.
        store.db.execute('UPDATE sends SET status=? WHERE owner=? AND id=?', (status, body.owner, str(body.request_id)))
        store.db.commit()
        return {'status': status}

    return routes
