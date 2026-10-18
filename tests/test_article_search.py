from contextlib import contextmanager

from fastapi.testclient import TestClient
from app.main import app, get_article_search


def test_search_returns_only_grounded_candidates_and_validates_query():
    seen = []
    def lookup(q):
        seen.append(q)
        return [{'seller_code': 'BRG-42', 'name': 'Rulment', 'supplier': 'Test', 'invoice_number': 'F1'}]
    app.dependency_overrides[get_article_search] = lambda: lookup
    try:
        client = TestClient(app)
        assert client.get('/articles/search', params={'q': '  rulment  '}).json()['items'][0]['seller_code'] == 'BRG-42'
        assert seen == ['rulment']
        for q in [' ', 'x', 'x' * 201]:
            assert client.get('/articles/search', params={'q': q}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_article_search)


def test_search_escapes_wildcards_and_binds_parameters(monkeypatch):
    calls = []
    class Conn:
        def execute(self, sql, params=None):
            calls.append((sql, params))
            return self
        def fetchall(self):
            return []
    @contextmanager
    def connect(*args, **kwargs):
        yield Conn()
    monkeypatch.setenv('DATABASE_URL', 'postgresql://unused')
    monkeypatch.setattr('app.main.psycopg.connect', connect)
    assert get_article_search()("%'_\\") == []
    assert calls[1][1] == {'pattern': "%\\%'\\_\\\\%"}
    assert 'LIMIT 20' in calls[1][0]
    assert 'statement_timeout' in calls[0][0]
