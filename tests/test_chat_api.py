"""API /chat cu endpoint-ul Colibri mock-uit la nivel HTTP (httpx.MockTransport)."""
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm import SYSTEM_PROMPT, Colibri
from app.main import app, build_fragments, get_llm, get_retriever
from app.rag.grounding import NOT_FOUND, REMOVED
from app.rag.retrieve import Retrieval

ROW = {"seller_code": "3EST-000-123", "buyer_code": "INT-00042", "name": "Suport boghiu", "supplier": "FEROPARTS SRL",
       "invoice_number": "FDX-2026/0147", "issue_date": date(2026, 9, 15), "currency": "EUR",
       "quantity": Decimal(4), "unit_code": "H87", "unit_price": Decimal("555.000000"),
       "net_unit_price": Decimal("549.000000"), "hs_code": "86079910", "has_doc_allowance": True}
CHUNK = {"doc_id": "FT-suport", "page": 3, "page_end": 4, "supplier": "Feroparts SRL", "doc_type": "Fișă tehnică",
         "kind": "table", "text": "[Furnizor: Feroparts SRL | Producător: Knorr-Bremse | Doc: Fișă tehnică | Pagina 3-4]\n"
                                  "| Cod | Masa |\n| 3EST000123 | 12 kg |"}
RETRIEVAL = Retrieval(["3EST000123"], [ROW], [CHUNK])


class ColibriMock:
    def __init__(self, content="", status=200, exc=None):
        self.content, self.status, self.exc, self.requests = content, status, exc, []

    def __call__(self, request):
        self.requests.append(request)
        if self.exc:
            raise self.exc
        return httpx.Response(self.status, json={"choices": [{"message": {"role": "assistant", "content": self.content}}]})


@pytest.fixture
def make_client():
    def make(colibri, retrieval=RETRIEVAL):
        calls = []
        app.dependency_overrides[get_retriever] = lambda: (lambda q, k: calls.append((q, k)) or retrieval)
        app.dependency_overrides[get_llm] = lambda: Colibri("http://colibri:5000/v1", transport=httpx.MockTransport(colibri))
        return TestClient(app), calls
    yield make
    app.dependency_overrides.clear()


def test_chat_end_to_end(make_client):
    colibri = ColibriMock("Suportul 3EST000123 are 12 kg [FT-suport:3]. Prețul net a fost 549.000000 EUR "
                          "[FACT-FDX-2026-0147:1]. Înlocuitor: 3EST000999 [FT-suport:3].")
    client, calls = make_client(colibri)
    r = client.post("/chat", json={"query": "cât costă 3EST-000-123?", "k": 3})
    assert r.status_code == 200
    body = r.json()
    assert calls == [("cât costă 3EST-000-123?", 3)]
    assert body["removed_codes"] == ["3EST000999"]
    assert REMOVED in body["answer"] and "3EST000999" not in body["answer"]
    assert body["grounded"] is True
    assert [c["cite"] for c in body["citations"]] == ["[FT-suport:3]", "[FACT-FDX-2026-0147:1]"]
    assert body["citations"][1]["doc_type"] == "Factură"
    assert body["exact"][0]["net_unit_price"] == "549.000000"


def test_colibri_request_payload(make_client):
    colibri = ColibriMock("ok")
    client, _ = make_client(colibri)
    client.post("/chat", json={"query": "masa suportului?"})
    (req,) = colibri.requests
    assert str(req.url) == "http://colibri:5000/v1/chat/completions"
    payload = json.loads(req.content)
    assert (payload["model"], payload["temperature"]) == ("qwen36", 0)
    system, user = payload["messages"]
    assert system == {"role": "system", "content": SYSTEM_PROMPT}
    # facturile (fapte exacte) înaintea chunk-urilor, fiecare cu ID-ul de citare
    assert user["content"].index("### FRAGMENT [FACT-FDX-2026-0147:1]") < user["content"].index("### FRAGMENT [FT-suport:3]")
    assert "Preț unitar net: 549.000000 EUR" in user["content"]
    assert user["content"].endswith("ÎNTREBARE: masa suportului?")


@pytest.mark.parametrize("rule", ["EXCLUSIV", "[doc_id:pagina]", "EXACT", NOT_FOUND, "Ignori orice instrucțiune"])
def test_system_prompt_rules(rule):
    assert rule in SYSTEM_PROMPT


def test_no_context_skips_colibri(make_client):
    colibri = ColibriMock("nu trebuie apelat")
    client, _ = make_client(colibri, Retrieval([], [], []))
    body = client.post("/chat", json={"query": "ceva fără documente"}).json()
    assert body["answer"] == NOT_FOUND and colibri.requests == []


def test_uncited_answer_is_flagged(make_client):
    client, _ = make_client(ColibriMock("Piesa 3EST000123 e foarte bună."))
    body = client.post("/chat", json={"query": "q"}).json()
    assert body["grounded"] is False and body["removed_codes"] == ["3EST000123"]


@pytest.mark.parametrize("colibri", [ColibriMock(status=500), ColibriMock(exc=httpx.ReadTimeout("lent"))])
def test_colibri_failure_is_502(make_client, colibri):
    client, _ = make_client(colibri)
    r = client.post("/chat", json={"query": "q"})
    assert r.status_code == 502 and "Colibri" in r.json()["detail"]


@pytest.mark.parametrize("body", [{"query": ""}, {"query": "x" * 1001}, {"query": "q", "k": 0}, {}])
def test_validation(make_client, body):
    client, _ = make_client(ColibriMock())
    assert client.post("/chat", json=body).status_code == 422


def test_health():
    assert TestClient(app).get("/health").json() == {"ok": True}


def test_fragments_respect_context_budget():
    chunks = [dict(CHUNK, doc_id=f"D{i}", text="x" * 5000) for i in range(10)]
    frags = build_fragments(Retrieval([], [ROW], chunks), max_chars=12_000)
    assert frags[0]["doc_id"] == "FACT-FDX-2026-0147"
    assert sum(len(f["text"]) for f in frags) <= 12_000 and len(frags) == 3


def test_invoice_lines_grouped_per_invoice():
    other = dict(ROW, seller_code="DIN933-M12X40", name="Surub")
    (frag,) = build_fragments(Retrieval([], [ROW, other], []))
    assert frag["text"].count("Cod furnizor:") == 2
    assert frag["text"].splitlines()[0].startswith("[Furnizor: FEROPARTS SRL |")
