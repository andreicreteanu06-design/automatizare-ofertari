"""Retriever hibrid: Qdrant real (mod in-memory) + embedder fals determinist în
locul BGE-M3 (care cere torch și 2 GB RAM). Postgres: fals, sau real cu TEST_DATABASE_URL."""
import hashlib
import math
import os
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from app.ingest.pdf import Chunk, DocMeta
from app.rag.index import COLLECTION, index_chunks, vector_search
from app.rag.retrieve import EXACT_SQL, code_candidates, exact_lookup, norm_code, retrieve

DIM = 64


class FakeEmbedder:
    """Dens: bag-of-words hașurat (cosinus ~ suprapunere de cuvinte). Sparse: id-uri de token."""
    dim = DIM

    def __init__(self, log=None):
        self.log, self.queries = log, []

    @staticmethod
    def _tok(word):
        return int(hashlib.md5(word.encode()).hexdigest(), 16)

    def embed(self, texts):
        texts = list(texts)
        self.queries += texts
        if self.log is not None:
            self.log.append("embed")
        out = []
        for t in texts:
            words = re.findall(r"\w+", t.lower())
            dense = [0.0] * DIM
            sparse = {}
            for w in words:
                dense[self._tok(w) % DIM] += 1
                sparse[self._tok(w) % 100_000] = sparse.get(self._tok(w) % 100_000, 0) + 1.0
            n = math.sqrt(sum(x * x for x in dense)) or 1
            out.append(([x / n for x in dense] if words else [1.0] + [0.0] * (DIM - 1), sparse))
        return out


class FakeConn:
    def __init__(self, rows=(), log=None):
        self.rows, self.log, self.calls = list(rows), log, []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if self.log is not None:
            self.log.append("postgres")
        return self

    def fetchall(self):
        return self.rows


META_A = DocMeta("FT-suport", "Feroparts SRL", "Knorr-Bremse", "Fișă tehnică")
META_B = DocMeta("CERT-iso", "Feroparts SRL", "Knorr-Bremse", "Certificat")


def chunk(meta, i, body, page=1, kind="text"):
    return Chunk(meta.doc_id, i, kind, page, page, None, f"[Furnizor: X | Producător: Y | Doc: Z | Pagina {page}]\n{body}")


@pytest.fixture
def qdrant():
    client = QdrantClient(":memory:")
    emb = FakeEmbedder()
    index_chunks(client, emb, [
        chunk(META_A, 0, "Suport boghiu otel S355 sudat EN 15085", page=2),
        chunk(META_A, 1, "| Cod | Masa |\n| 3EST000123 | 12 kg |", page=3, kind="table"),
        chunk(META_A, 2, "Montaj cuplu de strangere 80 Nm suruburi M12", page=4),
    ], META_A)
    index_chunks(client, emb, [chunk(META_B, 0, "Certificat ISO TS 22163 sistem de management feroviar")], META_B)
    return client


# --- Coduri candidate ---------------------------------------------------------------

@pytest.mark.parametrize("query,expected", [
    ("3EST000123", ["3EST000123"]),
    ("pret pentru 3EST-000-123?", ["3EST000123"]),
    ("3EST 000 123", ["3EST", "3EST000123"]),
    ("3est.000.123", ["3EST000123"]),
    ("DIN933-M12X40 si 5901234123457", ["5901234123457", "DIN933M12X40"]),
    ("suport boghiu din 2026", []),
    ("surub M12", []),
    ("", []),
])
def test_code_candidates(query, expected):
    assert code_candidates(query) == expected


def test_norm_code_matches_sql_generated_column():
    # aceeași regulă ca upper(regexp_replace(x, '[\s./-]', '', 'g')) din 001_invoices.sql
    sql = (Path(__file__).parents[1] / "backend" / "db" / "001_invoices.sql").read_text("utf-8")
    assert r"upper(regexp_replace(seller_code, '[\s./-]', '', 'g'))" in sql
    assert norm_code(" 3est-000/123.a ") == "3EST000123A"


# --- Qdrant hibrid ------------------------------------------------------------------

def test_vector_search_returns_cited_chunks(qdrant):
    hits = vector_search(qdrant, FakeEmbedder(), "cuplu strangere suruburi", k=2)
    assert hits[0]["doc_id"] == "FT-suport" and hits[0]["page"] == 4
    assert hits[0]["cite"] == "[FT-suport:4]"
    assert hits[0]["supplier"] == "Feroparts SRL" and hits[0]["doc_type"] == "Fișă tehnică"
    assert hits[0]["text"].startswith("[Furnizor:")


def test_sparse_catches_exact_code_token(qdrant):
    hits = vector_search(qdrant, FakeEmbedder(), "3EST000123", k=1)
    assert (hits[0]["kind"], hits[0]["page"]) == ("table", 3)


def test_reindex_replaces_document(qdrant):
    emb = FakeEmbedder()
    index_chunks(qdrant, emb, [chunk(META_A, 0, "Revizie noua suport", page=1)], META_A)
    assert qdrant.count(COLLECTION).count == 2  # 1 nou A + 1 B; vechile 3 chunk-uri A au dispărut
    hits = vector_search(qdrant, emb, "suport boghiu", k=5)
    assert {(h["doc_id"], h["page"]) for h in hits} == {("FT-suport", 1), ("CERT-iso", 1)}


def test_vector_search_without_collection_or_lexical_tokens():
    assert vector_search(QdrantClient(":memory:"), FakeEmbedder(), "orice") == []


def test_query_with_no_sparse_tokens(qdrant):
    assert len(vector_search(qdrant, FakeEmbedder(), "?!", k=2)) == 2  # doar prefetch dens


# --- retrieve(): întâi Postgres, apoi Qdrant -----------------------------------------

ROW = {"seller_code": "3EST-000-123", "buyer_code": None, "name": "Suport boghiu", "supplier": "FEROPARTS",
       "invoice_number": "FDX-1", "issue_date": date(2026, 9, 15), "currency": "EUR",
       "quantity": Decimal(4), "unit_code": "H87", "unit_price": Decimal(555), "net_unit_price": Decimal(549),
       "hs_code": "86079910", "has_doc_allowance": True}


def test_exact_path_runs_before_vector_search(qdrant):
    log = []
    conn, emb = FakeConn([ROW], log), FakeEmbedder(log)
    r = retrieve("pret 3EST-000-123", conn=conn, qdrant=qdrant, embedder=emb)
    assert log == ["postgres", "embed"]
    assert conn.calls == [(EXACT_SQL, {"codes": ["3EST000123"], "limit": 50})]
    assert r.codes == ["3EST000123"] and r.exact == [ROW]
    assert r.context and all("cite" in c for c in r.context)


def test_vector_query_enriched_with_exact_item_names(qdrant):
    emb = FakeEmbedder()
    r = retrieve("3EST000123", conn=FakeConn([ROW, ROW]), qdrant=qdrant, embedder=emb)
    assert emb.queries == ["3EST000123 Suport boghiu"]  # nume deduplicate
    assert r.context[0]["doc_id"] == "FT-suport"


def test_no_code_skips_postgres_but_still_searches(qdrant):
    conn = FakeConn()
    r = retrieve("certificare ISO feroviar", conn=conn, qdrant=qdrant, embedder=FakeEmbedder())
    assert conn.calls == [] and r.exact == []
    assert r.context[0]["doc_id"] == "CERT-iso"


def test_code_not_in_postgres_still_returns_context(qdrant):
    r = retrieve("3EST000123", conn=FakeConn([]), qdrant=qdrant, embedder=FakeEmbedder())
    assert r.exact == [] and r.context[0]["page"] == 3


# --- SQL real: rulează doar cu TEST_DATABASE_URL ------------------------------------

@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("setează TEST_DATABASE_URL pentru testele Postgres")
    import psycopg
    from psycopg.rows import dict_row
    schema = f"t_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(f"SET search_path TO {schema}")
        conn.execute((Path(__file__).parents[1] / "backend" / "db" / "001_invoices.sql").read_text("utf-8"))
        try:
            yield conn
        finally:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def test_exact_lookup_sql(db):
    from app.ingest.efactura import parse, store
    store(db, parse((Path(__file__).parent / "fixtures" / "synthetic" / "factura_eur.xml").read_bytes()))
    rows = exact_lookup(db, code_candidates("3est 000 123"))
    assert [(r["seller_code"], r["net_unit_price"]) for r in rows] == [("3EST-000-123", Decimal("549.000000"))]
    assert exact_lookup(db, ["INT00042"])[0]["buyer_code"] == "INT-00042"  # și după codul nostru
