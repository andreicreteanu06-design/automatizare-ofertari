"""Memory API contract, ownership and request replay with deterministic repository double."""
from copy import deepcopy
from uuid import uuid4
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import main
from app.main import app, get_llm, get_retriever
from app.memory import get_store, COOKIE
from app.rag.retrieve import Retrieval


class Store:
    def __init__(self):
        self.rows = {}
        self.turns = {}
    def create(self, owner, project, title):
        row = dict(id=str(uuid4()), project=project, title=title, version=0, messages=[], references=[])
        self.rows[row['id']] = (owner, row)
        return deepcopy(row)
    def load(self, owner, cid):
        entry = self.rows.get(str(cid))
        if not entry or entry[0] != owner:
            raise HTTPException(404, 'Conversație inexistentă')
        return deepcopy(entry[1])
    def list(self, owner):
        return [deepcopy(r) for o, r in self.rows.values() if o == owner]
    def previous(self, owner, cid, rid):
        self.load(owner, cid)
        return self.turns.get((str(cid), str(rid)))
    def append(self, owner, cid, version, rid, query, result):
        row = self.load(owner, cid)
        if row['version'] != version:
            raise HTTPException(409, 'Conflict')
        result = {**result, 'version': version+1, 'conversation_id': str(cid)}
        row['version'] += 1
        row['messages'] += [{'role':'user','text':query}, {'role':'assistant','data':result}]
        self.rows[str(cid)] = (owner, row)
        self.turns[str(cid), str(rid)] = {'query':query, 'response':result}
        return result
    def reference(self, owner, cid, evidence_id, note):
        row = self.load(owner, cid)
        evidence = next((e for m in row['messages'] if m['role']=='assistant' for e in m['data']['evidence'] if e['id']==evidence_id), None)
        if not evidence: raise HTTPException(422, 'Invalid evidence')
        self.rows[str(cid)][1]['references'].append({'id':1, 'evidence':evidence, 'note':note})
        return {'ok':True}


@pytest.fixture
def memory(monkeypatch):
    store = Store()
    calls = []
    app.dependency_overrides[get_store] = lambda: store
    monkeypatch.setattr(main, 'get_store', lambda: store)
    fragment = {'doc_id':'FT', 'page':1, 'text':'| Cod | Masa | Lungime |\n| --- | --- | --- |\n| PART123 | 12 kg | 120 mm |'}
    app.dependency_overrides[get_retriever] = lambda: lambda q,k: calls.append(q) or Retrieval(['PART123'], [], [fragment])
    class LLM:
        async def complete(self, messages):
            e = json.loads(messages[-1]['content'])['evidence']
            return json.dumps({'evidence_ids':[e[0]['id']]})
    app.dependency_overrides[get_llm] = LLM
    yield TestClient(app), store, calls
    app.dependency_overrides.clear()


def create(client):
    res=client.post('/conversations', json={'project':'Proiect A', 'title':'Suport'})
    assert res.status_code == 200
    assert 'HttpOnly' in res.headers['set-cookie'] and 'SameSite=strict' in res.headers['set-cookie']
    return res.json()['id']


def test_reload_followup_and_replay(memory):
    client, store, calls=memory
    cid=create(client)
    payload={'query':'masa PART123?', 'conversation_id':cid, 'version':0, 'request_id':str(uuid4())}
    response=client.post('/chat', json=payload)
    assert response.status_code==200
    assert response.json()['version']==1
    assert client.post('/chat',json=payload).json()==response.json()
    assert len(calls)==1
    second=TestClient(app)
    second.cookies.update(client.cookies)
    restored=second.get('/conversations/'+cid).json()
    assert len(restored['messages'])==2
    result=second.post('/chat',json={**payload,'query':'și lungimea?', 'version':1,'request_id':str(uuid4())})
    assert result.status_code==200 and 'PART123' in calls[-1]
    assert '120 mm' in result.json()['answer']
    assert len(second.get('/conversations/'+cid).json()['messages'])==4


def test_another_browser_cannot_read_or_write(memory):
    client,_,_=memory
    cid=create(client)
    other=TestClient(app)
    create(other)
    assert other.get('/conversations/'+cid).status_code==404
    assert other.post('/chat',json={'query':'q','conversation_id':cid,'version':0,'request_id':str(uuid4())}).status_code==404
    assert other.post('/conversations/'+cid+'/references',json={'evidence_id':'a'*24,'note':'x'}).status_code==404


def test_stale_version_and_request_id_reuse(memory):
    client,_,calls=memory
    cid=create(client)
    p={'query':'masa PART123?','conversation_id':cid,'version':0,'request_id':str(uuid4())}
    assert client.post('/chat',json=p).status_code==200
    assert client.post('/chat',json={**p,'request_id':str(uuid4())}).status_code==409
    assert client.post('/chat',json={**p,'query':'altă întrebare'}).status_code==409
    assert len(calls)==1


def test_references_are_saved_separately_not_promoted_to_facts(memory):
    client,_,_=memory
    cid=create(client)
    p={'query':'masa PART123?','conversation_id':cid,'version':0,'request_id':str(uuid4())}
    result=client.post('/chat',json=p).json()
    eid=result['evidence'][0]['id']
    assert client.post('/conversations/'+cid+'/references',json={'evidence_id':eid,'note':'Corecție propusă: 900 kg'}).status_code==200
    restored=client.get('/conversations/'+cid).json()
    assert restored['references'][0]['note'].endswith('900 kg')
    answer=client.post('/chat',json={**p,'query':'și masa?', 'version':1,'request_id':str(uuid4())}).json()
    assert '900 kg' not in answer['answer'] and '12 kg' in answer['answer']
