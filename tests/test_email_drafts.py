"""Draft-uri e-mail: Colibri și research-gateway mock-uite la nivel HTTP.
Gateway-ul fals rulează EgressGuard-ul REAL, cu un denylist de test."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm import Colibri
from app.main import app
from app.quoting.email import GuardClient, get_guard, get_translator
from research_gateway.app import create_app as gateway_app
from research_gateway.egress_guard import EgressBlocked, EgressGuard

GUARD = EgressGuard(["Acme Rail", "Proiect Delta"])
BASE = {"kind": "rfq", "language": "ro", "contact_name": "Hans Weber", "sender_name": "Ion Popescu",
        "sender_company": "Ofertant SRL",
        "items": [{"code": "3EST000123", "description": "Suport boghiu", "quantity": "4", "unit": "buc"},
                  {"code": "DIN933-M12X40", "description": "Surub", "quantity": "250"}],
        "reply_by": "2026-10-20"}


class Gateway:
    def __init__(self, status=200, payload=None):
        self.status, self.payload, self.calls = status, payload, []

    def __call__(self, request):
        texts = json.loads(request.content)["texts"]
        self.calls.append(texts)
        if self.payload is not None:
            return httpx.Response(self.status, json=self.payload)
        try:
            GUARD.check(texts)
            return httpx.Response(self.status, json={"ok": True, "rules": []})
        except EgressBlocked as e:
            return httpx.Response(self.status, json={"ok": False, "rules": e.rules})


class Llm:
    def __init__(self, content="", status=200):
        self.content, self.status, self.requests = content, status, []

    def __call__(self, request):
        self.requests.append(json.loads(request.content))
        return httpx.Response(self.status, json={"choices": [{"message": {"content": self.content}}]})


@pytest.fixture
def make():
    def build(gateway=None, llm=None):
        gateway, llm = gateway or Gateway(), llm or Llm()
        app.dependency_overrides[get_guard] = lambda: GuardClient("http://research-gateway:8000", httpx.MockTransport(gateway))
        app.dependency_overrides[get_translator] = lambda: Colibri("http://colibri:5000/v1", transport=httpx.MockTransport(llm))
        return TestClient(app), gateway, llm
    yield build
    app.dependency_overrides.clear()


GERMAN = ("SUBJECT: Angebotsanfrage – 3EST000123, DIN933-M12X40\nBODY:\nSehr geehrter Hans Weber,\n\n"
          "wir bitten um Ihr Angebot für folgende Artikel:\n\n1. 3EST000123 – Tragrahmen – Menge: 4 buc\n"
          "2. DIN933-M12X40 – Schraube – Menge: 250 pcs\n\nMit freundlichen Grüßen,\nIon Popescu\nOfertant SRL")


def test_romanian_rfq_is_deterministic(make):
    client, gw, llm = make()
    r = client.post("/emails/draft", json=BASE)
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "Cerere de ofertă – 3EST000123, DIN933-M12X40"
    for s in ["Stimate/Stimată Hans Weber,", "1. 3EST000123 – Suport boghiu – Cantitate: 4 buc",
              "2. DIN933-M12X40 – Surub – Cantitate: 250 pcs", "Incoterms", "până la 20.10.2026",
              "Cu stimă,\nIon Popescu\nOfertant SRL"]:
        assert s in body["body"], s
    assert body["translated"] is False and llm.requests == []
    assert gw.calls == [[body["subject"], body["body"]]]  # textul FINAL a trecut prin guard


def test_english_clarification(make):
    client, _, _ = make()
    r = client.post("/emails/draft", json={**BASE, "kind": "clarification", "language": "en",
                                           "questions": ["Is the bracket hot-dip galvanized?", "Weld class per EN 15085?"]})
    b = r.json()["body"]
    assert "Technical clarification" in r.json()["subject"]
    assert "Questions:\n1. Is the bracket hot-dip galvanized?\n2. Weld class per EN 15085?" in b


def test_clarification_without_questions_rejected(make):
    client, _, _ = make()
    assert client.post("/emails/draft", json={**BASE, "kind": "clarification"}).status_code == 422


def test_german_translated_by_colibri(make):
    client, gw, llm = make(llm=Llm(GERMAN))
    r = client.post("/emails/draft", json={**BASE, "language": "de"})
    assert r.status_code == 200, r.text
    assert r.json()["subject"].startswith("Angebotsanfrage") and r.json()["translated"] is True
    (req,) = llm.requests
    assert req["temperature"] == 0 and "into German" in req["messages"][0]["content"]
    assert "1. 3EST000123 – Suport boghiu" in req["messages"][1]["content"]  # sursa EN, coduri intacte
    assert len(gw.calls) == 2  # înainte de Colibri și pe textul final


def test_colibri_hallucinated_client_name_is_blocked(make):
    leaked = GERMAN.replace("folgende Artikel:", "folgende Artikel für das Projekt Acme Rail:")
    client, _, _ = make(llm=Llm(leaked))
    r = client.post("/emails/draft", json={**BASE, "language": "de"})
    assert r.status_code == 422
    assert r.json()["detail"]["rules"] == ["term#0"]
    assert "Angebot" not in r.text and "acme" not in r.text.lower()  # textul nu ajunge în UI


def test_client_name_in_input_blocked_before_colibri(make):
    client, _, llm = make(llm=Llm(GERMAN))
    bad = {**BASE, "language": "de", "kind": "clarification", "questions": ["Pentru Proiect Delta, ce varianta?"]}
    assert client.post("/emails/draft", json=bad).status_code == 422
    assert llm.requests == []


def test_client_name_blocked_in_deterministic_template_too(make):
    client, _, _ = make()
    r = client.post("/emails/draft", json={**BASE, "items": [{"code": "X1", "description": "pentru ACME-Rail"}]})
    assert r.status_code == 422


@pytest.mark.parametrize("content,key,value", [
    (GERMAN.replace("2. DIN933-M12X40", "2. DIN933-M12X4"), "missing_codes", ["DIN933-M12X40"]),
    (GERMAN.replace("Menge: 4 buc", "Menge: 4 buc (Alternative: 3EST000999)"), "invented_codes", ["3EST000999"]),
])
def test_translation_altering_codes_rejected(make, content, key, value):
    client, _, _ = make(llm=Llm(content))
    r = client.post("/emails/draft", json={**BASE, "language": "de"})
    assert r.status_code == 422 and r.json()["detail"][key] == value


@pytest.mark.parametrize("llm,status", [(Llm("Hier ist die Übersetzung ohne Format"), 502), (Llm(status=500), 502)])
def test_colibri_failures(make, llm, status):
    client, _, _ = make(llm=llm)
    assert client.post("/emails/draft", json={**BASE, "language": "fr"}).status_code == status


@pytest.mark.parametrize("gateway", [Gateway(status=500), Gateway(payload={"ok": "yes"}), Gateway(payload={})])
def test_guard_unavailable_or_unclear_fails_closed(make, gateway):
    client, _, _ = make(gateway=gateway)
    r = client.post("/emails/draft", json=BASE)
    assert r.status_code in (422, 503)
    assert "Cerere de ofert" not in r.text


def test_think_block_stripped_from_translation(make):
    client, _, _ = make(llm=Llm("<think>3EST000999?</think>\n" + GERMAN))
    assert client.post("/emails/draft", json={**BASE, "language": "de"}).status_code == 200


@pytest.mark.parametrize("bad", [{"language": "xx"}, {"items": []}, {"kind": "spam"}, {"sender_name": ""}])
def test_validation(make, bad):
    client, _, _ = make()
    assert client.post("/emails/draft", json={**BASE, **bad}).status_code == 422


def test_no_client_field_exists():
    from app.quoting.email import EmailDraftIn
    assert not any("client" in f or "project" in f for f in EmailDraftIn.model_fields)


# --- endpoint-ul real din research-gateway --------------------------------------------

def test_gateway_guard_check_endpoint():
    c = TestClient(gateway_app(GUARD))
    assert c.post("/guard/check", json={"texts": ["Anfrage 3EST000123"]}).json() == {"ok": True, "rules": []}
    assert c.post("/guard/check", json={"texts": ["ok", "für Acme  Rail"]}).json() == {"ok": False, "rules": ["term#0"]}
    assert c.post("/guard/check", json={"texts": []}).status_code == 422
