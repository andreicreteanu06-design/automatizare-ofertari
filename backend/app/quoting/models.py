"""Datele unei oferte. Sumele sunt Decimal: trimite-le ca șiruri în JSON ("12.50")."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

CURRENCY = Field(pattern=r"^[A-Za-z]{3}$")


class OfferLine(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    supplier: str = Field(min_length=1, max_length=200)
    manufacturer: str = Field("", max_length=200)
    quantity: Decimal = Field(gt=0)
    unit: str = Field("BUC", min_length=1, max_length=10)  # UM (Saga, Word)
    unit_price: Decimal = Field(ge=0)                  # preț de achiziție / unitate
    price_currency: str = CURRENCY
    transport_cost: Decimal = Field(Decimal(0), ge=0)  # TOTAL pe linie, până la livrare
    transport_currency: str = Field("EUR", pattern=r"^[A-Za-z]{3}$")
    duty_rate_percent: Decimal = Field(Decimal(0), ge=0, le=100)  # 0 pentru origine UE
    imported: bool = False                             # produs din afara României -> AFER
    afer_agreement: str | None = Field(None, max_length=100)


class SupplierCertificate(BaseModel):
    supplier: str = Field(min_length=1, max_length=200)
    standard: Literal["ISO/TS 22163", "ISO 9001"]
    number: str = Field(min_length=1, max_length=100)
    valid_until: date


class Offer(BaseModel):
    offer_number: str = Field(min_length=1, max_length=50)
    client_name: str = Field(min_length=1, max_length=200)
    offer_date: date
    validity_days: int = Field(30, ge=1, le=365)
    fx_date: date | None = None                        # implicit: data ofertei
    markup_percent: Decimal = Field(ge=0, le=1000)     # adaos peste costul total livrat
    delivery_terms: str = Field("DAP", max_length=100)
    # --- checklist de conformitate (validat în compliance.py) ---
    currency: str = "EUR"
    firm_prices: bool = False
    spare_parts_years: int = Field(0, ge=0)
    spare_parts_reference: str = Field("", max_length=200)
    include_penalty_clause: bool = False
    penalty_percent_per_week: Decimal = Decimal(5)
    penalty_cap_percent: Decimal = Decimal(30)
    certificates: list[SupplierCertificate] = []
    lines: list[OfferLine] = Field(min_length=1, max_length=500)
