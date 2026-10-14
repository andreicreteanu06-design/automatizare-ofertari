import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_fx
from app.quoting.saga import DATE_FORMAT, client_cif_ok, valid_ro_cui
from tests.test_quoting import FX, VALID

COMPANY = {"COMPANY_NAME": "Ofertant SRL", "COMPANY_CIF": "RO12345674", "COMPANY_REGCOM": "J40/1/2020",
           "COMPANY_CITY": "Bucuresti", "COMPANY_IBAN": "RO49AAAA1B31007593840000"}
SAGA = {**VALID, "client_cif": "RO12345674", "document_number": "OFT 0147", "vat_percent": "21"}
# Ordinea și numele tag-urilor din manualul Saga C (Import date -> facturi XML).
ANTET_TAGS = ["FurnizorNume", "FurnizorCIF", "FurnizorNrRegCom", "FurnizorTara", "FurnizorLocalitate",
              "FurnizorJudet", "FurnizorAdresa", "FurnizorBanca", "FurnizorIBAN", "ClientNume", "ClientCIF",
              "FacturaNumar", "FacturaData", "FacturaScadenta", "FacturaTaxareInversa", "FacturaTVAIncasare",
              "FacturaInformatiiSuplimentare", "FacturaMoneda"]
LINIE_TAGS = ["LinieNrCrt", "Descriere", "CodArticolFurnizor", "UM", "Cantitate", "Pret", "Valoare", "ProcTVA", "TVA"]


@pytest.fixture
def client(monkeypatch):
    for k, v in COMPANY.items():
        monkeypatch.setenv(k, v)

    async def fx(on):
        return FX
    app.dependency_overrides[get_fx] = lambda: fx
    yield TestClient(app)
    app.dependency_overrides.clear()


def export(client, **changes):
    return client.post("/offers/export/saga", json={**SAGA, **changes})


def test_structure_and_iesiri_routing(client):
    r = export(client)
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"] == 'attachment; filename="F_RO12345674_OFT-0147_13102026.xml"'
    assert r.content.startswith(b"<?xml version='1.0' encoding='utf-8'?>")
    root = ET.fromstring(r.content)
    assert root.tag == "Facturi" and [c.tag for c in root] == ["Factura"]
    antet = root.find("Factura/Antet")
    assert [c.tag for c in antet] == ANTET_TAGS
    assert antet.findtext("FurnizorCIF") == "RO12345674"  # = CIF-ul firmei din Saga -> Ieșiri
    assert (antet.findtext("ClientNume"), antet.findtext("ClientCIF")) == ("Client Feroviar SA", "RO12345674")
    assert (antet.findtext("FacturaNumar"), antet.findtext("FacturaData"), antet.findtext("FacturaScadenta")) == (
        "OFT 0147", "13.10.2026", "12.11.2026")
    assert antet.findtext("FacturaMoneda") == "RON"
    assert "Curs BNR 13.10.2026: 1 EUR = 5.0000 RON" in antet.findtext("FacturaInformatiiSuplimentare")


def test_lines_in_ron_at_offer_bnr_rate(client):
    lines = ET.fromstring(export(client).content).findall("Factura/Detalii/Continut/Linie")
    assert [[c.tag for c in l] for l in lines] == [LINIE_TAGS, LINIE_TAGS]
    values = [{c.tag: c.text for c in l} for l in lines]
    # 678.00 EUR × 5 = 3390 RON × 4 buc; TVA 21%
    assert values[0] == {"LinieNrCrt": "1", "Descriere": "Suport boghiu", "CodArticolFurnizor": "3EST000123",
                         "UM": "BUC", "Cantitate": "4", "Pret": "3390.0000", "Valoare": "13560.00",
                         "ProcTVA": "21", "TVA": "2847.60"}
    # 123.24 EUR × 5 = 616.20 RON × 10
    assert (values[1]["Pret"], values[1]["Valoare"], values[1]["TVA"]) == ("616.2000", "6162.00", "1294.02")


def test_custom_vat_and_dates(client):
    root = ET.fromstring(export(client, vat_percent="0", document_date="2026-10-20", due_days=0).content)
    assert root.findtext("Factura/Antet/FacturaData") == root.findtext("Factura/Antet/FacturaScadenta") == "20.10.2026"
    assert {l.findtext("TVA") for l in root.iter("Linie")} == {"0.00"}


def test_xml_escaping(client):
    lines = [{**VALID["lines"][0], "description": 'Suport <A&B> "special"'}]
    r = export(client, lines=lines)
    assert b"&lt;A&amp;B&gt;" in r.content
    assert ET.fromstring(r.content).findtext("Factura/Detalii/Continut/Linie/Descriere") == 'Suport <A&B> "special"'


def test_blocked_by_compliance_checklist(client):
    r = export(client, include_penalty_clause=False)
    assert r.status_code == 409 and r.json()["detail"]["failures"][0]["code"] == "PENALTY_CLAUSE"


@pytest.mark.parametrize("cif", ["RO12345675", "12345670", "RO", "ABC"])
def test_invalid_client_cif_rejected(client, cif):
    assert export(client, client_cif=cif).status_code == 422


def test_missing_company_config(client, monkeypatch):
    monkeypatch.delenv("COMPANY_CIF")
    r = export(client)
    assert r.status_code == 503 and "COMPANY_CIF" in r.json()["detail"]


@pytest.mark.parametrize("cif,ok", [
    ("12345674", True), ("RO12345674", True), ("ro 12345674", True),   # cifră de control calculată de mână
    ("12345675", False), ("RO1", False), ("RO12345678901", False),
])
def test_valid_ro_cui(cif, ok):
    assert valid_ro_cui(cif) is ok


@pytest.mark.parametrize("cif,ok", [("DE123456789", True), ("FR12345678901", True), ("RO12345675", False), ("X1", False)])
def test_client_cif_ok_accepts_eu_vat_ids(cif, ok):
    assert client_cif_ok(cif) is ok


# --- Comparare cu un XML generat de Saga însuși (cel mai sigur test de format) ----------

SAMPLES = sorted((Path(__file__).parent / "fixtures" / "saga").glob("*.xml"))


@pytest.mark.skipif(not SAMPLES, reason="pune în tests/fixtures/saga/ un XML generat de Saga (vezi app/quoting/saga.py)")
def test_matches_saga_generated_sample(client):
    sample = ET.parse(SAMPLES[0]).getroot()
    ours = ET.fromstring(export(client).content)
    sample_antet = {c.tag for c in sample.find("Factura/Antet")}
    assert {c.tag for c in ours.find("Factura/Antet")} <= sample_antet | {"FacturaMoneda"}
    from datetime import datetime
    datetime.strptime(sample.findtext("Factura/Antet/FacturaData"), DATE_FORMAT)  # aceeași formă a datei
    sample_pret = next(sample.iter("Pret")).text
    assert ("," in sample_pret) == ("," in next(ours.iter("Pret")).text), "separator zecimal diferit"
