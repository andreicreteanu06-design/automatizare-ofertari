"""Chat strict: only selected source excerpts may reach the response."""
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm import Colibri
from app.main import app, build_fragments, get_llm, get_retriever
from app.rag.grounding import NOT_FOUND
from app.rag.retrieve import Retrieval
from app.rag.evidence import source_units, contradictions, context_query

ROW = {'seller_code': '3EST-000-123', 'buyer_code': 'INT-00042', 'name': 'Suport boghiu', 'supplier': 'FEROPARTS',
       'invoice_number': 'F1', 'issue_date': date(2026, 9, 15), 'currency': 'EUR', 'quantity': Decimal(4),
       'unit_code': 'H87', 'unit_price': Decimal('555.000000'), 'net_unit_price': Decimal('549.000000'), 'hs_code': '86079910'}
CHUNK = {'doc_id': 'FT-suport', 'page': 3, 'page_end': 3, 'supplier': 'Feroparts', 'doc_type': 'Fișă tehnică',
         'source_revision': 'abc123', 'text': '| Cod | Masa | Lungime |\n| --- | --- | --- |\n| 3EST000123 | 12 kg | 120 mm |\n| OTHER999 | 120 kg | 20 mm |'}
RETRIEVAL = Retrieval(['3EST000123'], [ROW], [CHUNK])


@pytest.fixture
def make_client():
    def make(content=None, retrieval=RETRIEVAL):
        calls, requests = [], []
        def mock(request):
            payload = json.loads(request.content)
            requests.append(payload)
            evidence = json.loads(payload['messages'][-1]['content'])['evidence']
            answer = json.dumps({'evidence_ids': [evidence[0]['id']]}) if content is None else content
            return httpx.Response(200, json={'choices': [{'message': {'content': answer}}]})
        app.dependency_overrides[get_retriever] = lambda: lambda q, k: calls.append((q, k)) or retrieval
        app.dependency_overrides[get_llm] = lambda: Colibri('http://colibri:5000/v1', transport=httpx.MockTransport(mock))
        return TestClient(app), calls, requests
    yield make
    app.dependency_overrides.clear()


def test_exact_mass_and_row_binding(make_client):
    client, calls, requests = make_client()
    r = client.post('/chat', json={'query': 'masa 3EST000123?', 'k': 3})
    assert r.status_code == 200
    body = r.json()
    assert body['verification_status'] == 'verified_excerpts'
    assert 'Masa: 12 kg' in body['answer'] and '120 kg' not in body['answer']
    assert body['evidence'][0]['fields']['Lungime'] == '120 mm'
    assert body['evidence'][0]['source_revision'] == 'abc123'
    assert body['exact'][0]['net_unit_price'] == '549.000000'
    assert calls == [('masa 3EST000123?', 3)]
    assert requests[0]['temperature'] == 0


@pytest.mark.parametrize('content', [
    'Suportul 3EST000123 are masa 120 kg [FT-suport:3].',
    '{"evidence_ids": ["inventat"]}',
    '{"evidence_ids": [], "answer": "120 kg"}',
    'null', '{"evidence_ids": [123]}',
])
def test_invented_values_and_invalid_selection_fail_closed(make_client, content):
    client, calls, _ = make_client(content)
    body = client.post('/chat', json={'query': 'masa 3EST000123?'}).json()
    assert body['grounded'] is False
    assert body['answer'] == NOT_FOUND and '120 kg' not in body['answer']
    assert len(calls) == 3
    assert body['verification_status'] == 'insufficient_evidence'


def test_empty_results_expand_without_calling_model(make_client):
    client, calls, requests = make_client(retrieval=Retrieval([], [], []))
    body = client.post('/chat', json={'query': 'masa 3EST000123?', 'k': 3}).json()
    assert body['answer'] == NOT_FOUND and requests == []
    assert [k for _, k in calls] == [3, 6, 9]


def test_contradictions_block_single_value(make_client):
    other = dict(CHUNK, doc_id='FT-v2', text=CHUNK['text'].replace('12 kg', '13 kg'))
    client, _, requests = make_client(retrieval=Retrieval([], [], [CHUNK, other]))
    body = client.post('/chat', json={'query': 'masa 3EST000123?'}).json()
    assert body['verification_status'] == 'conflict' and body['grounded'] is False
    assert body['conflicts'][0]['values'] == ['12 kg', '13 kg']
    assert not requests


def test_unrelated_product_rows_are_excluded():
    units = source_units([CHUNK], 'masa OTHER999?')
    assert len(units) == 1 and units[0]['fields']['Masa'] == '120 kg'
    assert source_units([CHUNK], 'masa MISSING123?') == []


def test_history_carries_reference_not_assistant_claims():
    messages = [{'role': 'user', 'text': 'masa 3EST000123?'},
                {'role': 'assistant', 'data': {'answer': '999 kg WRONG999'}}]
    assert context_query('și lungimea?', messages) == 'și lungimea? 3EST000123'
    assert context_query('masa NEW999?', messages) == 'masa NEW999?'


def test_context_budget_skips_oversized_tables_without_truncating():
    big = dict(CHUNK, text='x' * 20000)
    frags = build_fragments(Retrieval([], [], [big, CHUNK]), max_chars=12000)
    assert frags == [dict(CHUNK, page_end=3)] or (len(frags) == 1 and frags[0]['text'] == CHUNK['text'])


@pytest.mark.parametrize('body', [{'query': ''}, {'query': 'x' * 1001}, {'query': 'q', 'k': 0}, {}])
def test_validation(make_client, body):
    client, _, _ = make_client()
    assert client.post('/chat', json=body).status_code == 422


def test_health():
    assert TestClient(app).get('/health').json() == {'ok': True}


def test_bounded_loop_recovers_after_invalid_model_output(make_client):
    client, calls, _ = make_client()
    class Repair:
        count = 0
        async def complete(self, messages):
            self.count += 1
            if self.count == 1:
                return '120 kg [FT-suport:3]'
            units = json.loads(messages[-1]['content'])['evidence']
            assert 'invalide' in messages[0]['content']
            return json.dumps({'evidence_ids': [units[0]['id']]})
    app.dependency_overrides[get_llm] = Repair
    body = client.post('/chat', json={'query': 'masa 3EST000123?'}).json()
    assert body['grounded'] and len(calls) == 2
    assert '120 kg' not in body['answer'] and '12 kg' in body['answer']


def test_prose_conflicts_and_ambiguous_headers():
    fragments = [dict(CHUNK, doc_id='A', text='3EST000123: masa 12 kg.'),
                 dict(CHUNK, doc_id='B', text='3EST000123: masa 13 kg.')]
    assert contradictions(source_units(fragments, 'masa 3EST000123?'))
    ambiguous = dict(CHUNK, text='| Cod | Masa | Masa |\n| 3EST000123 | 12 kg | 120 kg |')
    assert source_units([ambiguous], 'masa 3EST000123?') == []
