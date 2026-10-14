"""Checklist de conformitate BLOCANT pentru oferte către clientul feroviar.

Nu se bazează doar pe bife: fiecare cerință cere dovada ei (nr. agrement, nr. și
valabilitate certificat, referința confirmării) sau e verificată pe valorile reale
ale ofertei (monedă, parametrii penalităților). Lista goală = ofertă exportabilă.
"""
from dataclasses import dataclass
from decimal import Decimal

ALLOWED_STANDARDS = {"ISO/TS 22163", "ISO 9001"}
PENALTY_PER_WEEK, PENALTY_CAP = Decimal(5), Decimal(30)
SPARE_PARTS_MIN_YEARS = 30


@dataclass(frozen=True)
class Failure:
    code: str
    message: str


def _key(name):
    return " ".join(name.split()).casefold()


def check(offer):
    failures = []

    # 1. Agrement tehnic AFER pentru fiecare produs din import.
    for l in offer.lines:
        if l.imported and len((l.afer_agreement or "").strip()) < 3:
            failures.append(Failure("AFER_MISSING", f"{l.code}: produs din import fără agrement tehnic AFER"))

    # 2. Certificat ISO/TS 22163 sau ISO 9001, valabil la data ofertei, pentru fiecare furnizor.
    certs = {}
    for c in offer.certificates:
        if c.standard in ALLOWED_STANDARDS and c.number.strip():
            certs.setdefault(_key(c.supplier), []).append(c)
    for supplier in dict.fromkeys(l.supplier for l in offer.lines):
        valid = [c for c in certs.get(_key(supplier), []) if c.valid_until >= offer.offer_date]
        if not certs.get(_key(supplier)):
            failures.append(Failure("CERT_MISSING", f"{supplier}: lipsește certificatul ISO/TS 22163 sau ISO 9001"))
        elif not valid:
            failures.append(Failure("CERT_EXPIRED", f"{supplier}: certificatul a expirat înainte de {offer.offer_date}"))

    # 3. Piese de schimb disponibile minimum 30 de ani, cu referința confirmării.
    if offer.spare_parts_years < SPARE_PARTS_MIN_YEARS or not offer.spare_parts_reference.strip():
        failures.append(Failure("SPARE_PARTS_30Y",
                                "lipsește confirmarea (cu referință) a pieselor de schimb pentru minimum 30 de ani"))

    # 4. Clauza de penalități: exact 5%/săptămână, plafon 30%.
    if not (offer.include_penalty_clause and offer.penalty_percent_per_week == PENALTY_PER_WEEK
            and offer.penalty_cap_percent == PENALTY_CAP):
        failures.append(Failure("PENALTY_CLAUSE", "clauza de penalități trebuie inclusă: 5%/săptămână, maximum 30%"))

    # 5. Prețuri ferme, exclusiv în EUR.
    if offer.currency.upper() != "EUR":
        failures.append(Failure("CURRENCY_NOT_EUR", f"oferta trebuie exprimată în EUR, nu {offer.currency}"))
    if not offer.firm_prices:
        failures.append(Failure("PRICES_NOT_FIRM", "prețurile trebuie confirmate ca ferme"))

    return failures
