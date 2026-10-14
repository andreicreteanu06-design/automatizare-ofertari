"""Cursul de referință BNR (XML oficial). Rulează în research-gateway — singurul cu internet.

Cererea pleacă spre URL-uri fixe ale BNR, fără niciun parametru de la utilizator în afară
de an (int): nimic intern nu poate ieși pe aici.
Cursurile sunt RON pentru 1 unitate de monedă (multiplicatorul BNR, ex. HUF x100, e aplicat).
"""
import time
from datetime import date
from decimal import Decimal, InvalidOperation

from defusedxml.ElementTree import fromstring

# Verificat 2026-10-13: www.bnr.ro/nbrfxrates.xml face 302 spre pagina principală;
# fișierele sunt pe curs.bnr.ro. Namespace-ul diferă între fișiere (https:// în cel
# zilnic, http:// în arhivele anuale) -> elementele se caută după numele local.
DAILY_URL = "https://curs.bnr.ro/nbrfxrates.xml"
YEAR_URL = "https://curs.bnr.ro/files/xml/years/nbrfxrates{year}.xml"
_CACHE_SECONDS = {"daily": 3600, "year": 6 * 3600}
_cache = {}  # url -> (expiră_la, cubes)


class BnrError(Exception):
    pass


def _local(el, name):
    return el.tag == name or el.tag.endswith("}" + name)


def parse(xml):
    """{data: {monedă: Decimal RON/unitate}} din XML-ul BNR (zilnic sau anual)."""
    root = fromstring(xml)
    cubes = {}
    for cube in (el for el in root.iter() if _local(el, "Cube")):
        try:
            day = date.fromisoformat(cube.get("date", ""))
        except ValueError:
            raise BnrError(f"dată invalidă în XML-ul BNR: {cube.get('date')!r}") from None
        rates = {}
        for r in (el for el in cube if _local(el, "Rate")):
            cur = (r.get("currency") or "").upper()
            try:
                value = Decimal((r.text or "").strip()) / Decimal(r.get("multiplier") or 1)
            except (InvalidOperation, ZeroDivisionError):
                raise BnrError(f"curs invalid pentru {cur}") from None
            if len(cur) != 3 or not cur.isalpha() or value <= 0:
                raise BnrError(f"curs invalid pentru {cur!r}: {value}")
            rates[cur] = value
        if "EUR" not in rates:
            raise BnrError(f"lipsește EUR în cursul din {day}")
        cubes[day] = rates
    if not cubes:
        raise BnrError("XML BNR fără cursuri")
    return cubes


def pick(cubes, on):
    """Ultimul curs publicat la data `on` sau înainte (weekend/sărbători -> ziua lucrătoare anterioară)."""
    days = [d for d in cubes if d <= on]
    if not days:
        return None
    day = max(days)
    return day, cubes[day]


async def rates_for(on, get):
    """(data cursului, rates) pentru ziua `on`. `get(url) -> bytes` (injectat; httpx în producție)."""
    async def load(url, kind):
        hit = _cache.get(url)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        cubes = parse(await get(url))
        _cache[url] = (time.monotonic() + _CACHE_SECONDS[kind], cubes)
        return cubes

    daily = await load(DAILY_URL, "daily")
    if on >= max(daily):  # cursul de azi (sau o dată viitoare: ultimul publicat)
        return pick(daily, on)
    for year in (on.year, on.year - 1):  # 1-2 ianuarie nu au curs: anul anterior
        found = pick(await load(YEAR_URL.format(year=year), "year"), on)
        if found:
            return found
    raise BnrError(f"niciun curs BNR la sau înainte de {on}")
