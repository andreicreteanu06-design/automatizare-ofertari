import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from defusedxml import DefusedXmlException
from fastapi.testclient import TestClient

from research_gateway import bnr
from research_gateway.app import create_app
from research_gateway.egress_guard import EgressGuard


def cube(day, eur, extra=""):
    return f'<Cube date="{day}"><Rate currency="EUR">{eur}</Rate><Rate currency="USD">4.5000</Rate>{extra}</Cube>'


def dataset(*cubes, ns="http://www.bnr.ro/xsd"):
    return (f'<?xml version="1.0" encoding="utf-8"?><DataSet xmlns="{ns}">'
            '<Header><Publisher>National Bank of Romania</Publisher></Header>'
            f'<Body><Subject>Reference rates</Subject><OrigCurrency>RON</OrigCurrency>{"".join(cubes)}</Body>'
            '</DataSet>').encode()


# Ca în realitate: fișierul zilnic are namespace https://, arhivele anuale http://.
DAILY = dataset(cube("2026-10-13", "4.9763", '<Rate currency="HUF" multiplier="100">1.2500</Rate>'),
                ns="https://www.bnr.ro/xsd")
REAL_DAILY = (Path(__file__).parent / "fixtures" / "public" / "bnr_daily_real.xml").read_bytes()


def test_real_bnr_daily_file_parses():
    """Fișier descărcat de pe curs.bnr.ro (date publice) — formatul real, nu cel presupus."""
    ((day, rates),) = bnr.parse(REAL_DAILY).items()
    assert day.year >= 2026 and len(rates) > 25
    assert Decimal("4") < rates["EUR"] < Decimal("6")
    assert rates["HUF"] < Decimal("0.1")  # multiplicatorul 100 aplicat


def test_urls_point_to_curs_bnr_ro():
    assert bnr.DAILY_URL == "https://curs.bnr.ro/nbrfxrates.xml"
    assert bnr.YEAR_URL.format(year=2025) == "https://curs.bnr.ro/files/xml/years/nbrfxrates2025.xml"
YEAR_2026 = dataset(cube("2026-01-05", "4.9700"), cube("2026-10-09", "4.9750"), cube("2026-10-12", "4.9760"))
YEAR_2025 = dataset(cube("2025-12-30", "4.9690"), cube("2025-12-31", "4.9695"))


class FakeBnr:
    def __init__(self):
        self.urls = []
        self.files = {bnr.DAILY_URL: DAILY, bnr.YEAR_URL.format(year=2026): YEAR_2026,
                      bnr.YEAR_URL.format(year=2025): YEAR_2025}

    async def __call__(self, url):
        self.urls.append(url)
        return self.files[url]


@pytest.fixture(autouse=True)
def clear_cache():
    bnr._cache.clear()


def rates_for(on, fake=None):
    return asyncio.run(bnr.rates_for(on, fake or FakeBnr()))


def test_parse_applies_multiplier():
    (rates,) = bnr.parse(DAILY).values()
    assert rates == {"EUR": Decimal("4.9763"), "USD": Decimal("4.5000"), "HUF": Decimal("0.0125")}


def test_today_uses_daily_file_only():
    fake = FakeBnr()
    assert rates_for(date(2026, 10, 13), fake)[0] == date(2026, 10, 13)
    assert fake.urls == [bnr.DAILY_URL]


def test_weekend_uses_previous_business_day():
    day, rates = rates_for(date(2026, 10, 11))  # duminică
    assert (day, rates["EUR"]) == (date(2026, 10, 9), Decimal("4.9750"))


def test_new_year_falls_back_to_previous_year():
    day, rates = rates_for(date(2026, 1, 2))
    assert (day, rates["EUR"]) == (date(2025, 12, 31), Decimal("4.9695"))


def test_cache_avoids_refetch():
    fake = FakeBnr()
    asyncio.run(bnr.rates_for(date(2026, 10, 13), fake))
    asyncio.run(bnr.rates_for(date(2026, 10, 13), fake))
    assert fake.urls == [bnr.DAILY_URL]


@pytest.mark.parametrize("xml,match", [
    (dataset(cube("2026-10-13", "-1")), "invalid"),
    (dataset(cube("2026-10-13", "abc")), "invalid"),
    (dataset('<Cube date="2026-10-13"><Rate currency="USD">4.5</Rate></Cube>'), "EUR"),
    (dataset(cube("13.10.2026", "4.97")), "dată"),
    (dataset(), "fără cursuri"),
])
def test_invalid_bnr_xml_rejected(xml, match):
    with pytest.raises(bnr.BnrError, match=match):
        bnr.parse(xml)


def test_xxe_rejected():
    with pytest.raises(DefusedXmlException):
        bnr.parse(b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
                  b'<DataSet xmlns="http://www.bnr.ro/xsd">&e;</DataSet>')


def client(get):
    return TestClient(create_app(EgressGuard(["Acme Rail"]), bnr_get=get))


def test_fx_endpoint():
    body = client(FakeBnr()).get("/fx/bnr", params={"date": "2026-10-11"}).json()
    assert body == {"source": "BNR", "date": "2026-10-09", "rates": {"EUR": "4.9750", "USD": "4.5000"}}


def test_fx_endpoint_bnr_down_is_502():
    async def down(url):
        raise bnr.BnrError("timeout")
    assert client(down).get("/fx/bnr").status_code == 502


def test_fx_endpoint_bad_date_is_422():
    assert client(FakeBnr()).get("/fx/bnr", params={"date": "ieri"}).status_code == 422
