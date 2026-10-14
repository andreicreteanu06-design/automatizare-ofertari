"""Verificări statice ale UI-ului (fără Node/browser): sintaxă JS, legături JS<->HTML,
JS<->API backend și regulile de securitate."""
import re
from pathlib import Path

import esprima
import pytest

from app.main import app

ROOT = Path(__file__).parents[1]
# Regresii pentru interfața originală păstrată în legacy.
# SPA-ul React este verificat separat prin frontend/tests/*.spec.js (Playwright).
JS = (ROOT / "frontend" / "legacy" / "app.js").read_text("utf-8")
HTML = (ROOT / "frontend" / "legacy" / "index.html").read_text("utf-8")
NGINX = (ROOT / "infra" / "nginx" / "default.conf").read_text("utf-8")


def test_js_parses():
    esprima.parseScript(JS)  # aruncă la orice eroare de sintaxă


def test_every_id_used_in_js_exists_in_html():
    used = set(re.findall(r'\$\("#([\w-]+)', JS)) | set(re.findall(r'"#([\w-]+)[ "]', JS))
    defined = set(re.findall(r'id="([\w-]+)"', HTML))
    assert used and used <= defined, used - defined


def test_every_form_field_used_in_js_exists_in_html():
    used = set(re.findall(r'elements\.(\w+)', JS)) | set(re.findall(r'\b(?:val|v)\("(\w+)"\)', JS))
    defined = set(re.findall(r'name="(\w+)"', HTML))
    assert used <= defined, used - defined


def test_every_api_call_has_a_backend_route():
    # Schema OpenAPI (publică) — app.routes e internă; FastAPI ≥0.14x include router-ele leneș.
    routes = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    calls = re.findall(r'api\("(/[\w/.-]+)', JS)
    assert set(calls) >= {"/chat", "/prices", "/offers/calculate", "/offers/export/", "/emails/draft"}
    for path in calls:
        if path.endswith("/"):  # /offers/export/ + kind
            assert {("POST", path + k) for k in ("docx", "xlsx", "saga")} <= routes
        else:
            assert any(p == path for _, p in routes), path


def test_offer_payload_fields_match_backend_model():
    from app.quoting.models import Offer, OfferLine, SupplierCertificate
    body = re.search(r"function offerPayload\(\)[\s\S]+?\n}\n", JS).group(0)
    offer_keys = set(re.findall(r"\b(\w+):", body))
    assert set(Offer.model_fields) <= offer_keys | {"fx_date"}
    assert set(OfferLine.model_fields) <= offer_keys
    cert_fields = set(re.findall(r'name: "(\w+)"', JS[JS.index("function addCert"):JS.index("function rowValues")]))
    assert cert_fields == set(SupplierCertificate.model_fields)


@pytest.mark.parametrize("pattern", [r"\.innerHTML", r"\.outerHTML", r"insertAdjacentHTML", r"document\.write", r"\beval\(", r"new Function"])
def test_no_html_injection_sinks(pattern):
    assert not re.search(pattern, JS)


def test_no_external_resources():
    for src in (HTML, JS, (ROOT / "frontend" / "legacy" / "styles.css").read_text("utf-8")):
        assert not re.search(r"https?://|//cdn|@import", src)
    assert "style=" not in HTML  # CSP style-src 'self' blochează stilurile inline


def test_nginx_security_headers():
    assert "default-src 'self'" in NGINX and "frame-ancestors 'none'" in NGINX
    assert 'add_header Cache-Control "no-store" always' in NGINX
    assert "proxy_pass http://backend:8000/;" in NGINX


def test_downloads_gated_on_compliance_and_fresh_calculation():
    # butoanele pornesc dezactivate și se activează DOAR pe compliance.ok, după un calcul proaspăt
    for b in ("dl-docx", "dl-xlsx", "dl-saga"):
        assert f'id="{b}" disabled' in HTML
    assert '$("#dl-docx").disabled = $("#dl-xlsx").disabled = $("#dl-saga").disabled = !res.compliance.ok' in JS
    assert re.search(r"function markStale\(\)[\s\S]+?disabled = true", JS)
