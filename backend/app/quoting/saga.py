"""Export XML pentru importul în Saga C la „Ieșiri” (Diverse -> Import date).

Structura și numele tag-urilor: manualul oficial Saga C, secțiunea „Import date”
(manual.sagasoft.ro/sagac/topic-76-import-date.html). Saga trimite factura la IEȘIRI când
<FurnizorCIF> este CIF-ul firmei deschise în Saga — de aceea furnizorul = firma noastră (din .env).

NEVERIFICAT (manualul nu le specifică): formatul datei, separatorul zecimal, TVA ca sumă.
Sunt izolate mai jos. Verificare: în Saga, tipărește o factură de ieșire cu „Formular PDF”
-> Saga scrie și un XML model în C:\\TEMP\\Facturi; pune-l în tests/fixtures/saga/ și
testul test_matches_saga_generated_sample îl compară automat cu exportul nostru.
"""
import os
import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import Field

from app.quoting.models import Offer

DATE_FORMAT = "%d.%m.%Y"   # NEVERIFICAT — vezi docstring
PRICE_Q = Decimal("0.0001")
MONEY_Q = Decimal("0.01")

_CUI_KEY = "753217532"


def valid_ro_cui(cui):
    """Cifra de control a CUI-ului românesc (cheia 753217532). Acceptă prefixul RO."""
    digits = re.sub(r"^RO", "", re.sub(r"\s", "", cui.upper()))
    if not digits.isdigit() or not 2 <= len(digits) <= 10:
        return False
    body, control = digits[:-1].zfill(9), int(digits[-1])
    c = sum(int(a) * int(b) for a, b in zip(body, _CUI_KEY)) * 10 % 11
    return (0 if c == 10 else c) == control


def client_cif_ok(cif):
    """CUI românesc (cifre, opțional RO) -> cifra de control; cod TVA UE străin -> doar formatul."""
    s = re.sub(r"\s", "", cif.upper())
    if re.fullmatch(r"(RO)?\d+", s):
        return valid_ro_cui(s)
    return re.fullmatch(r"[A-Z]{2}[A-Z0-9]{2,13}", s) is not None


class SagaExportIn(Offer):
    client_cif: str = Field(min_length=2, max_length=20)
    document_number: str = Field(min_length=1, max_length=30)   # numărul din Saga (serie + nr.)
    document_date: date | None = None                           # implicit: data ofertei
    due_days: int = Field(30, ge=0, le=365)
    vat_percent: Decimal = Field(Decimal(21), ge=0, le=100)     # 21% = cota standard RO din 08.2025


def company_from_env():
    """Firma noastră (furnizorul de pe Ieșiri). COMPANY_CIF e obligatoriu: decide ruta Ieșiri."""
    cif = os.environ.get("COMPANY_CIF", "").strip()
    if not cif:
        return None
    return {k: os.environ.get(f"COMPANY_{k.upper()}", "").strip()
            for k in ("name", "cif", "regcom", "address", "city", "county", "iban", "bank")}


def _fmt(value, q):
    return str(value.quantize(q, ROUND_HALF_UP))


def _sub(parent, tag, text):
    ET.SubElement(parent, tag).text = "" if text is None else str(text)


def build_xml(req, calc, company):
    """(nume_fișier, bytes) — Pret în RON la cursul BNR folosit în ofertă."""
    eur_ron = calc.fx.rate("EUR")
    doc_date = req.document_date or req.offer_date
    due = date.fromordinal(doc_date.toordinal() + req.due_days)

    root = ET.Element("Facturi")
    factura = ET.SubElement(root, "Factura")
    antet = ET.SubElement(factura, "Antet")
    for tag, value in [
        ("FurnizorNume", company["name"]), ("FurnizorCIF", company["cif"]),
        ("FurnizorNrRegCom", company["regcom"]), ("FurnizorTara", "RO"),
        ("FurnizorLocalitate", company["city"]), ("FurnizorJudet", company["county"]),
        ("FurnizorAdresa", company["address"]), ("FurnizorBanca", company["bank"]),
        ("FurnizorIBAN", company["iban"]),
        ("ClientNume", req.client_name), ("ClientCIF", req.client_cif.strip().upper()),
        ("FacturaNumar", req.document_number), ("FacturaData", doc_date.strftime(DATE_FORMAT)),
        ("FacturaScadenta", due.strftime(DATE_FORMAT)),
        ("FacturaTaxareInversa", "Nu"), ("FacturaTVAIncasare", "Nu"),
        ("FacturaInformatiiSuplimentare",
         f"Conform oferta {req.offer_number}. Curs BNR {calc.fx.date.strftime('%d.%m.%Y')}: 1 EUR = {eur_ron} RON"),
        ("FacturaMoneda", "RON"),
    ]:
        _sub(antet, tag, value)

    continut = ET.SubElement(ET.SubElement(factura, "Detalii"), "Continut")
    for n, c in enumerate(calc.lines, 1):
        price_ron = (c.sale_unit_eur * eur_ron).quantize(PRICE_Q, ROUND_HALF_UP)
        value = (price_ron * c.line.quantity).quantize(MONEY_Q, ROUND_HALF_UP)
        vat = (value * req.vat_percent / 100).quantize(MONEY_Q, ROUND_HALF_UP)
        linie = ET.SubElement(continut, "Linie")
        for tag, v in [("LinieNrCrt", n), ("Descriere", c.line.description), ("CodArticolFurnizor", c.line.code),
                       ("UM", c.line.unit), ("Cantitate", f"{c.line.quantity.normalize():f}"),
                       ("Pret", _fmt(price_ron, PRICE_Q)), ("Valoare", _fmt(value, MONEY_Q)),
                       ("ProcTVA", f"{req.vat_percent.normalize():f}"), ("TVA", _fmt(vat, MONEY_Q))]:
            _sub(linie, tag, v)

    ET.indent(root)
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    safe = lambda s: re.sub(r"[^A-Za-z0-9-]+", "-", s).strip("-")  # noqa: E731
    name = f"F_{safe(company['cif'])}_{safe(req.document_number)}_{doc_date.strftime('%d%m%Y')}.xml"
    return name, data
