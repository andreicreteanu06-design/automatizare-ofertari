"""Parsare e-Factura (UBL 2.1, RO CIUS) -> istoric exact de prețuri de achiziție.

Acceptă .xml (Invoice / CreditNote) și arhivele .zip descărcate din SPV ANAF
(factura + semnatura_*.xml; semnătura e ignorată). XML-ul vine de la terți:
parsare cu defusedxml (fără entități externe / expansiuni).

Două prețuri pe linie, pentru că diferă des:
  unit_price      = PriceAmount / BaseQuantity      (prețul de listă de pe factură)
  net_unit_price  = LineExtensionAmount / Quantity  (după reducerile de pe linie)
"""
import hashlib
import re
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from defusedxml.ElementTree import fromstring

_NS = {"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
       "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}
_ROOTS = {"{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice":
          ("invoice", "cac:InvoiceLine", "cbc:InvoicedQuantity"),
          "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote":
          ("credit_note", "cac:CreditNoteLine", "cbc:CreditedQuantity")}
MAX_XML_BYTES = 20 * 2**20  # protecție zip-bomb: o factură reală are sub 1 MB


class InvoiceError(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    line_no: str
    name: str
    description: str | None
    seller_code: str | None   # codul furnizorului (SellersItemIdentification)
    buyer_code: str | None    # codul nostru, dacă furnizorul îl trece
    std_code: str | None      # GTIN etc. (StandardItemIdentification)
    hs_code: str | None       # cod vamal NC/HS, dacă e clasificat așa -> taxe vamale
    quantity: Decimal
    unit_code: str | None
    unit_price: Decimal | None
    net_unit_price: Decimal | None
    line_amount: Decimal
    vat_percent: Decimal | None


@dataclass(frozen=True)
class Invoice:
    doc_type: str             # "invoice" | "credit_note"
    number: str
    issue_date: date
    currency: str
    supplier_name: str
    supplier_tax_id: str
    payable_amount: Decimal | None
    doc_allowance: Decimal    # reduceri la nivel de document (nedistribuite pe linii)
    sha256: str
    lines: list[Line] = field(default_factory=list)


def _text(el, path):
    found = el.find(path, _NS)
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def _dec(el, path):
    t = _text(el, path)
    if t is None:
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        raise InvoiceError(f"număr invalid la {path}: {t!r}") from None


def _required(value, what):
    if value is None:
        raise InvoiceError(f"lipsește {what}")
    return value


def _tax_id(party):
    # PartyLegalEntity/CompanyID e des nr. Registrului Comerțului (J40/...), nu CUI: sărit.
    candidates = ("".join((_text(party, p) or "").split()).upper() for p in (
        "cac:PartyTaxScheme/cbc:CompanyID", "cac:PartyLegalEntity/cbc:CompanyID", "cac:PartyIdentification/cbc:ID"))
    raw = _required(next((c for c in candidates if c and not re.match(r"[JFC]\d{1,2}/", c)), None), "CUI furnizor")
    return raw[2:] if raw.startswith("RO") and raw[2:].isdigit() else raw  # RO123 == 123


def _line(el, qty_path):
    qty = _required(_dec(el, qty_path), "cantitate")
    amount = _required(_dec(el, "cbc:LineExtensionAmount"), "valoare linie")
    price, base = _dec(el, "cac:Price/cbc:PriceAmount"), _dec(el, "cac:Price/cbc:BaseQuantity")
    qty_el = el.find(qty_path, _NS)
    hs = next((c.text.strip() for c in el.findall("cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode", _NS)
               if c.get("listID") in ("HS", "NC", "TARIC") and c.text), None)
    return Line(
        line_no=_required(_text(el, "cbc:ID"), "ID linie"),
        name=_required(_text(el, "cac:Item/cbc:Name"), "denumire articol"),
        description=_text(el, "cac:Item/cbc:Description"),
        seller_code=_text(el, "cac:Item/cac:SellersItemIdentification/cbc:ID"),
        buyer_code=_text(el, "cac:Item/cac:BuyersItemIdentification/cbc:ID"),
        std_code=_text(el, "cac:Item/cac:StandardItemIdentification/cbc:ID"),
        hs_code=hs,
        quantity=qty,
        unit_code=qty_el.get("unitCode"),
        unit_price=None if price is None else price / (base or 1),
        net_unit_price=amount / qty if qty else None,
        line_amount=amount,
        vat_percent=_dec(el, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"),
    )


def parse(data: bytes) -> Invoice:
    if len(data) > MAX_XML_BYTES:
        raise InvoiceError("fișier XML prea mare")
    root = fromstring(data)
    if root.tag not in _ROOTS:
        raise InvoiceError(f"nu e factură UBL 2.1: {root.tag}")
    doc_type, line_path, qty_path = _ROOTS[root.tag]
    party = _required(root.find("cac:AccountingSupplierParty/cac:Party", _NS), "furnizor")
    lines = [_line(el, qty_path) for el in root.findall(line_path, _NS)]
    if not lines:
        raise InvoiceError("factură fără linii")
    allowances = [_dec(a, "cbc:Amount") or 0 for a in root.findall("cac:AllowanceCharge", _NS)
                  if _text(a, "cbc:ChargeIndicator") == "false"]
    try:
        issue = date.fromisoformat(_required(_text(root, "cbc:IssueDate"), "dată emitere"))
    except ValueError:
        raise InvoiceError("dată emitere invalidă") from None
    return Invoice(
        doc_type=doc_type,
        number=_required(_text(root, "cbc:ID"), "număr factură"),
        issue_date=issue,
        currency=_required(_text(root, "cbc:DocumentCurrencyCode"), "monedă").upper(),
        supplier_name=_required(_text(party, "cac:PartyLegalEntity/cbc:RegistrationName")
                                or _text(party, "cac:PartyName/cbc:Name"), "nume furnizor"),
        supplier_tax_id=_tax_id(party),
        payable_amount=_dec(root, "cac:LegalMonetaryTotal/cbc:PayableAmount"),
        doc_allowance=sum(allowances, Decimal(0)),
        sha256=hashlib.sha256(data).hexdigest(),
        lines=lines,
    )


def _is_ubl(data):
    head = data[:2048]
    return b"Invoice-2" in head or b"CreditNote-2" in head


def read_file(path) -> list[Invoice]:
    """Facturile dintr-un .xml sau .zip ANAF (semnăturile și alte XML-uri sunt sărite)."""
    path = Path(path)
    if path.suffix.lower() != ".zip":
        return [parse(path.read_bytes())]
    out = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".xml"):
                continue
            if info.file_size > MAX_XML_BYTES:
                raise InvoiceError(f"{info.filename}: prea mare în arhivă")
            data = z.read(info)
            if _is_ubl(data):
                out.append(parse(data))
    if not out:
        raise InvoiceError(f"{path.name}: nicio factură UBL în arhivă")
    return out


# --- Postgres -------------------------------------------------------------------

_LINE_COLS = ("line_no", "name", "description", "seller_code", "buyer_code", "std_code", "hs_code",
              "quantity", "unit_code", "unit_price", "net_unit_price", "line_amount", "vat_percent")


def store(conn, inv: Invoice):
    """Inserează factura (idempotent). Întoarce id-ul sau None dacă exista deja
    (același fișier, sau același furnizor + număr + tip)."""
    with conn.transaction():
        if conn.execute("SELECT 1 FROM invoice WHERE source_sha256 = %s", (inv.sha256,)).fetchone():
            return None
        supplier_id = conn.execute(
            "INSERT INTO supplier (tax_id, name) VALUES (%s, %s) "
            "ON CONFLICT (tax_id) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            (inv.supplier_tax_id, inv.supplier_name)).fetchone()[0]
        row = conn.execute(
            "INSERT INTO invoice (supplier_id, doc_type, number, issue_date, currency, payable_amount,"
            " doc_allowance, source_sha256) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (supplier_id, doc_type, number) DO NOTHING RETURNING id",
            (supplier_id, inv.doc_type, inv.number, inv.issue_date, inv.currency,
             inv.payable_amount, inv.doc_allowance, inv.sha256)).fetchone()
        if row is None:
            return None
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO invoice_line (invoice_id, {', '.join(_LINE_COLS)}) "
                f"VALUES (%s, {', '.join(['%s'] * len(_LINE_COLS))})",
                [(row[0], *(getattr(l, c) for c in _LINE_COLS)) for l in inv.lines])
        return row[0]


def main(paths):
    """python -m app.ingest.efactura data/inbox/*.zip   (folosește DATABASE_URL)"""
    import os

    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for p in paths:
            try:
                ids = [store(conn, inv) for inv in read_file(p)]
                print(f"{p}: {sum(i is not None for i in ids)} noi, {sum(i is None for i in ids)} existente")
            except InvoiceError as e:
                print(f"{p}: RESPINS — {e}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
