"""Postgres-backed browser workspaces. Cookie capability is NOT enterprise login."""
import hashlib
import os
import secrets
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix='/conversations', tags=['Memory'])
COOKIE = 'ofertare_workspace'


class MemoryStore:
    def __init__(self, dsn):
        self.dsn = dsn
        # Also migrates existing volumes: initdb scripts only run on empty volumes.
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(73489322)')
            conn.execute((Path(__file__).resolve().parents[1] / 'db/002_memory.sql').read_text('utf-8'))

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5,
                               options='-c statement_timeout=10000')

    def create(self, owner, project, title):
        with self.connect() as conn:
            row = conn.execute('INSERT INTO chat_conversation(id,owner_hash,project,title) VALUES(%s,%s,%s,%s) RETURNING *',
                               (uuid4(), owner, project, title)).fetchone()
        return {k: v for k, v in row.items() if k != 'owner_hash'}

    def list(self, owner):
        with self.connect() as conn:
            return conn.execute('SELECT id,project,title,version,updated_at FROM chat_conversation WHERE owner_hash=%s ORDER BY updated_at DESC', (owner,)).fetchall()

    def load(self, owner, cid):
        with self.connect() as conn:
            # One consistent snapshot even if another tab completes a turn meanwhile.
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            row = conn.execute('SELECT id,project,title,version FROM chat_conversation WHERE id=%s AND owner_hash=%s', (cid, owner)).fetchone()
            if not row:
                raise HTTPException(404, 'Conversație inexistentă în acest spațiu.')
            turns = conn.execute('SELECT query,response,request_id FROM (SELECT * FROM chat_turn WHERE conversation_id=%s ORDER BY id DESC LIMIT 100) t ORDER BY id', (cid,)).fetchall()
            row['messages'] = [m for t in turns for m in ({'role': 'user', 'text': t['query']}, {'role': 'assistant', 'data': t['response']})]
            row['references'] = conn.execute('SELECT id,evidence,note,created_at FROM chat_reference WHERE conversation_id=%s ORDER BY id DESC LIMIT 100', (cid,)).fetchall()
            return row

    def previous(self, owner, cid, request_id):
        with self.connect() as conn:
            row = conn.execute('SELECT t.query,t.response FROM chat_turn t JOIN chat_conversation c ON c.id=t.conversation_id WHERE c.id=%s AND c.owner_hash=%s AND t.request_id=%s', (cid, owner, request_id)).fetchone()
            return row

    def append(self, owner, cid, version, request_id, query, result):
        with self.connect() as conn:
            row = conn.execute('SELECT version FROM chat_conversation WHERE id=%s AND owner_hash=%s FOR UPDATE', (cid, owner)).fetchone()
            if not row:
                raise HTTPException(404, 'Conversație inexistentă.')
            old = conn.execute('SELECT query,response FROM chat_turn WHERE conversation_id=%s AND request_id=%s', (cid, request_id)).fetchone()
            if old:
                if old['query'] != query or old['response'].get('live_web', False) != result.get('live_web', False):
                    raise HTTPException(409, 'ID-ul cererii a fost deja folosit pentru altă întrebare.')
                return old['response']
            if row['version'] != version:
                raise HTTPException(409, 'Conversația s-a modificat în alt tab. Reîncarcă istoricul.')
            result = {**result, 'conversation_id': str(cid), 'version': version + 1}
            conn.execute('INSERT INTO chat_turn(conversation_id,request_id,query,response) VALUES(%s,%s,%s,%s)', (cid, request_id, query, Jsonb(result)))
            conn.execute('UPDATE chat_conversation SET version=version+1,updated_at=now() WHERE id=%s', (cid,))
        return result

    def reference(self, owner, cid, evidence_id, note):
        data = self.load(owner, cid)
        evidence = next((e for m in reversed(data['messages']) if m['role'] == 'assistant'
                         for e in m['data'].get('evidence', []) if e['id'] == evidence_id), None)
        if not evidence:
            raise HTTPException(422, 'Referința trebuie selectată din dovezile conversației.')
        with self.connect() as conn:
            conn.execute('INSERT INTO chat_reference(conversation_id,evidence,note) VALUES(%s,%s,%s)', (cid, Jsonb(evidence), note))
        return {'ok': True}


@lru_cache
def _store():
    return MemoryStore(os.environ['DATABASE_URL'])


def get_store():
    try:
        return _store()
    except (psycopg.Error, KeyError):
        raise HTTPException(503, 'Memoria persistentă nu este disponibilă. Verifică Postgres.') from None


def owner(request: Request):
    token = request.cookies.get(COOKIE, '')
    if len(token) < 40 or len(token) > 100:
        raise HTTPException(401, 'Spațiul browserului nu este inițializat. Creează o conversație.')
    return hashlib.sha256(token.encode()).hexdigest()


class ConversationIn(BaseModel):
    project: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)


class ReferenceIn(BaseModel):
    evidence_id: str = Field(pattern=r'^[a-f0-9]{24}$')
    note: str = Field(default='', max_length=1000)


@router.post('')
def create(body: ConversationIn, request: Request, response: Response, store=Depends(get_store)):
    token = request.cookies.get(COOKIE)
    if not token or not 40 <= len(token) <= 100:
        token = secrets.token_urlsafe(48)
    result = store.create(hashlib.sha256(token.encode()).hexdigest(), body.project, body.title)
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict',
                        secure=os.getenv('COOKIE_SECURE', 'false').lower() == 'true', max_age=365 * 86400, path='/')
    return result


@router.get('')
def listing(request: Request, store=Depends(get_store)):
    if not request.cookies.get(COOKIE):
        return []
    return store.list(owner(request))


@router.get('/{cid}')
def read(cid: UUID, request: Request, store=Depends(get_store)):
    return store.load(owner(request), cid)


@router.post('/{cid}/references')
def remember(cid: UUID, body: ReferenceIn, request: Request, store=Depends(get_store)):
    return store.reference(owner(request), cid, body.evidence_id, body.note)
