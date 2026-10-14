import os
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from defusedxml import DefusedXmlException

from app.ingest.efactura import InvoiceError, parse, read_file, store

FIX = Path(__file__).parent / "fixtures" / "synthetic"
INVOICE = (FIX / "factura_eur.xml").read_bytes()
CREDIT = (FIX / "nota_credit.xml").read_bytes()


def test_invoice_header():
    inv = parse(INVOICE)
    assert (inv.doc_type, inv.number, inv.issue_date, inv.currency) == (
        "invoice", "FDX-2026-0147", date(2026, 9, 15), "EUR")
    assert (inv.supplier_name, inv.supplier_tax_id) == ("FEROPARTS DISTRIBUTIE SRL", "12345678")
    assert inv.payable_amount == Decimal("2994.04")
    assert inv.doc_allowance == Decimal("50.00")  # taxa de ambalare (charge) nu e reducere
    assert len(inv.sha256) == 64


def test_line_codes_and_classification():
    l1 = parse(INVOICE).lines[0]
    assert (l1.line_no, l1.name, l1.description) == ("1", "Suport boghiu", "Suport cadru boghiu, otel S355")
    assert (l1.seller_code, l1.buyer_code, l1.std_code) == ("3EST-000-123", "INT-00042", "5901234123457")
    assert l1.hs_code == "86079910"  # CPV (listID=STI) e ignorat
    assert (l1.quantity, l1.unit_code, l1.vat_percent) == (Decimal(4), "H87", Decimal(19))


def test_prices_list_vs_net_and_base_quantity():
    l1, l2 = parse(INVOICE).lines
    assert (l1.unit_price, l1.net_unit_price) == (Decimal("555.00"), Decimal("549"))  # reducere pe linie
    assert (l2.unit_price, l2.net_unit_price) == (Decimal("1.4"), Decimal("1.4"))     # 140 EUR / 100 buc
    assert l2.hs_code is None and l2.buyer_code is None


def test_credit_note():
    cn = parse(CREDIT)
    assert (cn.doc_type, cn.number, cn.currency) == ("credit_note", "NC-2026-0003", "RON")
    assert (cn.supplier_name, cn.supplier_tax_id) == ("Feroparts", "12345678")  # fallback-uri
    assert cn.lines[0].quantity == 1 and cn.doc_allowance == 0


def test_same_supplier_with_and_without_ro_prefix():
    assert parse(INVOICE).supplier_tax_id == parse(CREDIT).supplier_tax_id


def _without(xml, fragment):
    assert fragment in xml
    return xml.replace(fragment, b"")


@pytest.mark.parametrize("fragment,error", [
    (b"<cbc:ID>FDX-2026-0147</cbc:ID>", "număr factură"),
    (b"<cbc:IssueDate>2026-09-15</cbc:IssueDate>", "dată emitere"),
    (b"<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>", "monedă"),
    (b"<cbc:CompanyID>RO 12345678</cbc:CompanyID>", "CUI"),  # J40/1/2020 nu e acceptat drept CUI
    (b'<cbc:InvoicedQuantity unitCode="H87">4</cbc:InvoicedQuantity>', "cantitate"),
])
def test_missing_fields(fragment, error):
    with pytest.raises(InvoiceError, match=error):
        parse(_without(INVOICE, fragment))


def test_bad_values_rejected():
    with pytest.raises(InvoiceError, match="dată"):
        parse(INVOICE.replace(b"2026-09-15<", b"15.09.2026<"))
    with pytest.raises(InvoiceError, match="număr invalid"):
        parse(INVOICE.replace(b">555.00<", b">555,00<"))


def test_no_lines_rejected():
    start, end = INVOICE.index(b"<cac:InvoiceLine>"), INVOICE.rindex(b"</cac:InvoiceLine>") + 18
    with pytest.raises(InvoiceError, match="fără linii"):
        parse(INVOICE[:start] + INVOICE[end:])


def test_not_ubl_rejected():
    with pytest.raises(InvoiceError, match="nu e factură"):
        parse(b"<Order xmlns='urn:x'><ID>1</ID></Order>")


@pytest.mark.parametrize("payload", [
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
    b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&e;</Invoice>',
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&b;</Invoice>',
])
def test_xml_attacks_rejected(payload):
    with pytest.raises(DefusedXmlException):
        parse(payload)


def test_anaf_zip_skips_signature(tmp_path):
    z = tmp_path / "4567890123.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("4567890123.xml", INVOICE)
        f.writestr("semnatura_4567890123.xml",
                   '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"><SignatureValue>x</SignatureValue></Signature>')
        f.writestr("readme.txt", "x")
    (inv,) = read_file(z)
    assert inv.number == "FDX-2026-0147"


def test_zip_without_invoice_rejected(tmp_path):
    z = tmp_path / "gol.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("semnatura.xml", "<Signature/>")
    with pytest.raises(InvoiceError, match="nicio factură"):
        read_file(z)


def test_plain_xml_file():
    assert read_file(FIX / "nota_credit.xml")[0].doc_type == "credit_note"


# --- Integrare Postgres: rulează doar cu TEST_DATABASE_URL setat -------------------

@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("setează TEST_DATABASE_URL pentru testele Postgres")
    import psycopg
    schema = f"t_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(f"SET search_path TO {schema}")
        conn.execute((Path(__file__).parents[1] / "backend" / "db" / "001_invoices.sql").read_text("utf-8"))
        try:
            yield conn
        finally:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def test_store_idempotent_and_price_history(db):
    assert store(db, parse(INVOICE)) is not None
    assert store(db, parse(INVOICE)) is None                        # același fișier
    assert store(db, parse(INVOICE.replace(b"<!-- F", b"<!-- f"))) is None  # alt fișier, același număr
    assert store(db, parse(CREDIT)) is not None
    rows = db.execute("SELECT seller_code_norm, net_unit_price, supplier FROM price_history"
                      " WHERE seller_code_norm = %s", ("3EST000123",)).fetchall()
    assert rows == [("3EST000123", Decimal("549.000000"), "FEROPARTS DISTRIBUTIE SRL")]
    assert db.execute("SELECT count(*) FROM supplier").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM price_history").fetchone()[0] == 2  # fără nota de credit
