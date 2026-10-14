"""research-gateway: singurul serviciu cu acces la internet.

POST /research: interogare -> Egress Guard -> SearXNG -> URL-uri (Egress Guard,
doar http(s) publice) -> Playwright MCP (HTML + innerText) -> extract() -> Laya
-> rânduri cu status "verified" sau "unverified" (afișat „Neverificat” în UI).

Răspunsurile de pe internet nu decid nimic singure: un rând e "verified" doar
dacă extractorul determinist găsește codul în textul vizibil ȘI Laya confirmă.
"""
import ipaddress
import json
import os
import re
from datetime import date
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Query
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, Field

from research_gateway import bnr
from research_gateway.egress_guard import EgressBlocked, load
from research_gateway.extract import extract, find_code, page_text

LAYA_WINDOW = 500  # caractere de context în jurul codului trimise lui Laya
PAGE_JS = ("() => JSON.stringify({html: document.documentElement.outerHTML,"
           " text: document.body ? document.body.innerText : ''})")


def public_http(url):
    """Doar http(s) spre adrese publice: browserul stă pe rețeaua egress și ar putea
    altfel atinge router-ul sau alte mașini din LAN.
    shortcut: nume DNS care rezolvă spre IP-uri private nu sunt prinse aici —
    upgrade: --blocked-origins în Playwright sau firewall pe rețeaua egress."""
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return host != "localhost" and not host.endswith((".local", ".internal", ".localhost"))


def parse_evaluate(text):
    """Rezultatul lui browser_evaluate e text liber (format nedocumentat): acceptă
    JSON brut, string JSON (dublu codat), secțiune '### Result' și blocuri ```."""
    m = re.search(r"### Result\s*\n(.*?)(?=\n### |\Z)", text, re.S)
    body = (m[1] if m else text).strip()
    body = re.sub(r"^```\w*\s*\n|\n```\s*$", "", body).strip()
    value = json.loads(body)
    return json.loads(value) if isinstance(value, str) else value


async def searxng_search(query):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(os.environ["SEARXNG_URL"] + "/search", params={"q": query, "format": "json"})
        r.raise_for_status()
        return [x["url"] for x in r.json().get("results", []) if x.get("url")]


async def mcp_fetch(url):
    """(html, innerText) pentru URL, prin Playwright MCP (o sesiune izolată per pagină)."""
    async with streamable_http_client(os.environ["PLAYWRIGHT_MCP_URL"]) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for tool, args in (("browser_navigate", {"url": url}), ("browser_evaluate", {"function": PAGE_JS})):
                r = await session.call_tool(tool, args)
                text = "".join(c.text for c in r.content if getattr(c, "type", None) == "text")
                if r.is_error:
                    raise RuntimeError(f"{tool}: {text[:200]}")
    page = parse_evaluate(text)
    return page["html"], page["text"]


async def laya_verify(code, text):
    """P(codul apare literal în text), de la Laya (/v1/systemone, întrebare noul)."""
    body = {"model": "laya", "state": text, "questions": {"present": {
        "type": "noul", "instructions": f"Does the exact product code {code} appear literally in this text?"}}}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(os.environ["LAYA_URL"], json=body)
        r.raise_for_status()
        return float(r.json()["answers"]["present"]["noul"])


async def research(code, query, max_pages, *, guard, search, fetch, verify, threshold):
    guard.check({"q": query})  # EgressBlocked -> nimic nu pleacă
    results, errors, seen, blocked = [], [], set(), 0
    for url in await search(query):
        if len(seen) >= max_pages:
            break
        if url in seen or not public_http(url):
            continue
        try:
            guard.check(url)
        except EgressBlocked:
            blocked += 1  # URL-ul nu e raportat: poate conține chiar textul sensibil
            continue
        seen.add(url)
        try:
            html, inner = await fetch(url)
            hits = extract(html, code, url, inner_text=inner)
        except Exception as e:  # o pagină stricată nu oprește restul căutării
            errors.append({"url": url, "error": f"{type(e).__name__}: {str(e)[:300]}"})
            continue
        if not hits:
            continue
        score = None
        text = page_text(html, inner)
        spans = find_code(text, code)
        if spans:  # codul nu e în textul vizibil -> nu are sens să întrebăm Laya
            s, e, _ = spans[0]
            try:
                score = await verify(code, text[max(0, s - LAYA_WINDOW):e + LAYA_WINDOW])
            except Exception as ex:
                errors.append({"url": url, "error": f"laya: {type(ex).__name__}: {str(ex)[:300]}"})
        verified = score is not None and score >= threshold
        results += [{"url": h.url, "code": h.code, "price": str(h.price), "currency": h.currency,
                     "source": h.source, "code_on_page": h.code_on_page, "laya_score": score,
                     "status": "verified" if verified and h.code_on_page else "unverified",
                     "context": h.context} for h in hits]
    return {"query": query, "results": results, "errors": errors, "blocked_urls": blocked}


class GuardIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=50)


class ResearchIn(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    query: str | None = Field(None, max_length=200)
    max_pages: int = Field(5, ge=1, le=10)


async def http_get(url):
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


def create_app(guard=None, search=searxng_search, fetch=mcp_fetch, verify=laya_verify, threshold=None,
               bnr_get=http_get):
    guard = guard or load()  # fail-closed: fără denylist validă, serviciul nu pornește
    threshold = threshold if threshold is not None else float(os.environ.get("LAYA_THRESHOLD", 0.9))
    app = FastAPI(title="research-gateway")

    @app.post("/guard/check")
    def guard_check(body: GuardIn):
        """Verifică orice text care urmează să plece din firmă (ex. e-mailuri către furnizori).
        Un singur denylist, o singură implementare: backend-ul nu deține lista."""
        try:
            guard.check(body.texts)
            return {"ok": True, "rules": []}
        except EgressBlocked as e:
            return {"ok": False, "rules": e.rules}

    @app.get("/fx/bnr")
    async def fx_bnr(on: date | None = Query(None, alias="date")):
        """Cursul BNR valabil la data cerută (implicit azi), RON / 1 unitate, ca șiruri exacte."""
        try:
            day, rates = await bnr.rates_for(on or date.today(), bnr_get)
        except (bnr.BnrError, httpx.HTTPError) as e:
            raise HTTPException(502, f"curs BNR indisponibil: {type(e).__name__}: {str(e)[:200]}") from None
        return {"source": "BNR", "date": day.isoformat(), "rates": {k: str(v) for k, v in sorted(rates.items())}}

    @app.post("/research")
    async def research_endpoint(body: ResearchIn):
        try:
            return await research(body.code, body.query or body.code, body.max_pages, guard=guard,
                                  search=search, fetch=fetch, verify=verify, threshold=threshold)
        except EgressBlocked as e:
            raise HTTPException(403, {"blocked": e.rules})

    @app.get("/health")
    def health():
        return {"ok": True}

    return app
