"""Cursul BNR, cerut de la research-gateway prin rețeaua internă (backend-ul nu are internet)."""
import os
from datetime import date
from decimal import Decimal

import httpx

from app.quoting.engine import FxError, FxSnapshot


async def bnr_snapshot(on, transport=None):
    url = os.environ["RESEARCH_GATEWAY_URL"].rstrip("/") + "/fx/bnr"
    async with httpx.AsyncClient(timeout=60, transport=transport) as client:
        r = await client.get(url, params={"date": on.isoformat()})
        r.raise_for_status()
        data = r.json()
    if data.get("source") != "BNR" or "EUR" not in data.get("rates", {}):
        raise FxError("răspuns invalid de la research-gateway pentru cursul BNR")
    return FxSnapshot(date.fromisoformat(data["date"]), {k: Decimal(v) for k, v in data["rates"].items()})
