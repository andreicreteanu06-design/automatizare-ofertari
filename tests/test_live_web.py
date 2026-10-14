import asyncio
import json

import httpx
from fastapi.testclient import TestClient
import pytest

from research_gateway.app import create_app
from research_gateway.egress_guard import EgressGuard
from app.rag import live_web
from app.rag.evidence import answer_question
from app.rag.retrieve import Retrieval


def test_guard_precedes_search_and_no_sensitive_text_in_error():
    calls = []
    async def search(q):
        calls.append(q)
        return []
    client = TestClient(create_app(guard=EgressGuard(['SecretClient']), search=search))
    r = client.post('/live-research', json={'query': 'SecretClient PART123'})
    assert r.status_code == 403 and not calls
    assert 'SecretClient' not in r.text


def test_top_three_public_urls_parallel_and_total_budget():
    fetched, active = [], []
    async def search(q):
        return ['http://127.0.0.1', 'https://shop.example/SecretClient', *[f'https://shop{i}.example/p' for i in range(5)]]
    async def fetch(url):
        fetched.append(url)
        active.append(len(fetched))
        await asyncio.sleep(.01)
        assert len(fetched) == 3  # all three scheduled before any finishes
        return '<p>hidden</p>', 'PART123 masa 12 kg. ' * 1000
    client = TestClient(create_app(guard=EgressGuard(['SecretClient']), search=search, fetch=fetch))
    result = client.post('/live-research', json={'query': 'PART123 masa'}).json()
    assert fetched == [f'https://shop{i}.example/p' for i in range(3)]
    assert len(result['text']) <= 10000
    assert len(result['sources']) == 3
    assert sum(len(s['text']) for s in result['sources']) <= 10000
    assert 'hidden' not in result['text'] and result['blocked_urls'] == 1


def test_partial_failure_is_reported_without_exception_details():
    async def search(q):
        return ['https://a.example', 'https://b.example']
    async def fetch(url):
        if 'a.example' in url:
            raise TimeoutError('private trace SecretClient')
        return '', 'PART123 masa 12 kg'
    client = TestClient(create_app(guard=EgressGuard(['SecretClient']), search=search, fetch=fetch))
    result = client.post('/live-research', json={'query': 'PART123'}).json()
    assert len(result['sources']) == 1 and len(result['errors']) == 1
    assert 'SecretClient' not in json.dumps(result)


def test_visible_html_table_cells_remain_bound_to_their_headers():
    from app.rag.evidence import source_units
    fragment = {'doc_id': 'https://supplier.example', 'page': 1,
                'text': 'Cod\tMasa\nPART123\t12 kg\nOTHER999\t120 kg', 'source_type': 'web'}
    units = source_units([fragment], 'Masa PART123?')
    assert len(units) == 1 and units[0]['fields']['Masa'] == '12 kg'


def test_search_failure_is_502():
    async def search(q):
        raise httpx.ConnectError('internal details')
    client = TestClient(create_app(guard=EgressGuard(['SecretClient']), search=search))
    r = client.post('/live-research', json={'query': 'PART123'})
    assert r.status_code == 502 and 'internal details' not in r.text


def test_opt_in_only_current_question_leaves_and_url_is_cited(monkeypatch):
    sent = []
    async def live(q):
        sent.append(q)
        return [{'doc_id': 'https://supplier.example/PART123', 'page': 1, 'text': 'PART123 masa 12 kg.',
                 'source_type': 'web', 'url': 'https://supplier.example/PART123'}], {'sources': ['https://supplier.example/PART123'], 'errors': []}
    monkeypatch.setattr(live_web, 'fetch_live', live)
    def retrieval(q, k):
        return Retrieval([], [], [])
    class Model:
        async def complete(self, messages):
            units = json.loads(messages[-1]['content'])['evidence']
            return json.dumps({'evidence_ids': [units[0]['id']]})
    history = [{'role': 'user', 'text': 'SecretClient PART123 preț intern 555 EUR'}]
    async def run():
        internal = await answer_question('masa?', 5, history, retrieval, Model())
        assert not sent and not internal['live_web']
        return await answer_question('masa?', 5, history, retrieval, Model(), live_web=True)
    result = asyncio.run(run())
    assert sent == ['masa?']
    assert '[https://supplier.example/PART123]' in result['answer']
    assert result['citations'][0]['url'] == 'https://supplier.example/PART123'
    assert 'SecretClient' not in json.dumps(result)
