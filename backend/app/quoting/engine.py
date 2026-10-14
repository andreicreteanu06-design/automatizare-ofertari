"""Costul Total Livrat (Landed Cost) și prețul de vânzare, în EUR, pe unitate.

    preț_EUR    = preț × curs(monedă) / curs(EUR)          (curs BNR: RON / 1 unitate)
    transport   = transport_linie_EUR / cantitate
    taxă_vamală = (preț_EUR + transport) × cotă / 100
    landed      = preț_EUR + transport + taxă_vamală
    vânzare     = round_half_up(landed × (1 + adaos / 100), 0.01)
    total_linie = vânzare × cantitate

Calcul intern la precizie completă; se rotunjește o singură dată, la prețul de vânzare,
ca totalul din ofertă să fie exact vânzare × cantitate (cum va apărea pe factură).
TVA nu intră în cost (deductibil). shortcut: valoarea în vamă include tot transportul;
legal contează doar transportul până la granița UE — upgrade: câmp separat pentru el.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
Q4 = Decimal("0.0001")


class FxError(ValueError):
    pass


@dataclass(frozen=True)
class FxSnapshot:
    date: date
    rates: dict  # monedă -> Decimal RON pentru 1 unitate

    def rate(self, currency):
        r = self.rates.get(currency.upper())
        if r is None or r <= 0:
            raise FxError(f"lipsește cursul BNR pentru {currency.upper()} la {self.date}")
        return r

    def to_eur(self, amount, currency):
        cur = currency.upper()
        if cur == "EUR":
            return amount
        ron = amount if cur == "RON" else amount * self.rate(cur)
        return ron / self.rate("EUR")


@dataclass(frozen=True)
class LineCalc:
    line: object
    price_eur: Decimal          # / unitate
    transport_eur: Decimal      # / unitate
    duty_eur: Decimal           # / unitate
    landed_eur: Decimal         # / unitate
    sale_unit_eur: Decimal      # / unitate, rotunjit la cent
    sale_total_eur: Decimal
    margin_eur: Decimal         # pe linie


@dataclass(frozen=True)
class OfferCalc:
    lines: list
    fx: FxSnapshot
    markup_percent: Decimal
    total_landed_eur: Decimal
    total_sale_eur: Decimal
    total_margin_eur: Decimal

    @property
    def margin_on_sale_percent(self):
        """Marja reală raportată la vânzare (≠ adaos): 25% adaos = 20% marjă."""
        if not self.total_sale_eur:
            return Decimal(0)
        return (self.total_margin_eur / self.total_sale_eur * 100).quantize(CENT, ROUND_HALF_UP)


def calc_line(line, fx, markup_percent):
    price = fx.to_eur(line.unit_price, line.price_currency)
    transport = fx.to_eur(line.transport_cost, line.transport_currency) / line.quantity
    duty = (price + transport) * line.duty_rate_percent / 100
    landed = price + transport + duty
    sale_unit = (landed * (1 + markup_percent / 100)).quantize(CENT, ROUND_HALF_UP)
    total = (sale_unit * line.quantity).quantize(CENT, ROUND_HALF_UP)
    return LineCalc(line, price.quantize(Q4, ROUND_HALF_UP), transport.quantize(Q4, ROUND_HALF_UP),
                    duty.quantize(Q4, ROUND_HALF_UP), landed.quantize(Q4, ROUND_HALF_UP), sale_unit, total,
                    (total - landed * line.quantity).quantize(CENT, ROUND_HALF_UP))


def calc_offer(offer, fx):
    lines = [calc_line(l, fx, offer.markup_percent) for l in offer.lines]
    total_sale = sum((c.sale_total_eur for c in lines), Decimal(0))
    total_landed = sum((c.landed_eur * c.line.quantity for c in lines), Decimal(0)).quantize(CENT, ROUND_HALF_UP)
    return OfferCalc(lines, fx, offer.markup_percent, total_landed, total_sale,
                     sum((c.margin_eur for c in lines), Decimal(0)))
