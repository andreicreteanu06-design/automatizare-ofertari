"""research-gateway: intermediarul backend-ului pentru acces extern controlat.

POST /research: interogare -> Egress Guard -> SearXNG -> URL-uri (Egress Guard,
doar http(s) publice) -> Camoufox (HTML + innerText) -> extract() -> Laya
-> rânduri cu status "verified" sau "unverified" (afișat „Neverificat” în UI).

Răspunsurile de pe internet nu decid nimic singure: un rând e "verified" doar
dacă extractorul determinist găsește codul în textul vizibil ȘI Laya confirmă.
"""
import asyncio
import ipaddress
import json
import os
from datetime import date
from datetime import datetime, timezone
from collections import OrderedDict
import time
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from research_gateway import bnr
from research_gateway.egress_guard import EgressBlocked, load
from research_gateway.extract import extract, find_code, page_text
from research_gateway.quality import access_check, authority, load_policy


class PageCache:
    """Bounded process-local fallback; never silently presented as current data."""
    def __init__(self):
        self.rows = OrderedDict()

    def put(self, url, page):
        self.rows[url] = (time.monotonic(), dict(page))
        self.rows.move_to_end(url)
        while len(self.rows) > 100:
            self.rows.popitem(last=False)

    def get(self, url):
        row = self.rows.get(url)
        if row and time.monotonic() - row[0] < 86400:
            return dict(row[1], stale=True)
        return None

LAYA_WINDOW = 500  # caractere de context în jurul codului trimise lui Laya
def public_http(url):
    """Cheap URL filter; authoritative DNS/IP checks run in the browser proxy."""
    try:
        p = urlsplit(url)
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
                or p.port not in (None, 80, 443) or "\\" in url or any(ord(c) < 33 for c in url)):
            return False
        host = p.hostname.rstrip('.').lower()
        if host == 'localhost' or host.endswith(('.local', '.internal', '.localhost')):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if getattr(ip, 'ipv4_mapped', None):
                ip = ip.ipv4_mapped
            return ip.is_global and not (ip.is_multicast or ip.is_reserved)
        except ValueError:
            return '.' in host
    except ValueError:
        return False


async def searxng_search(query):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(os.environ["SEARXNG_URL"] + "/search", params={"q": query, "format": "json"})
        r.raise_for_status()
        return [x["url"] for x in r.json().get("results", []) if x.get("url")]


async def browser_fetch(url):
    """Plain HTTP to isolated Camoufox service; no browser protocol in the gateway."""
    async with httpx.AsyncClient(timeout=170, trust_env=False) as client:
        response = await client.post(os.environ['STEALTH_BROWSER_URL'].rstrip('/') + '/fetch', json={'url': url})
        response.raise_for_status()
        data = response.json()
        return data


def unpack_page(page, original):
    if isinstance(page, dict):
        return page['html'], page['text'], page.get('url', original)
    return *page, original  # compatibility with injected test fetchers


async def live_research(query, *, guard, search, fetch, policy=None, cache=None):
    # Only the user's current question is accepted. No history or internal documents.
    guard.check({'query': query})
    policy = policy or {}
    urls, blocked = [], 0
    ranked = sorted((await search(query))[:30], key=lambda u: {'manufacturer': 0, 'authorized_distributor': 1, 'secondary': 2}[authority(u, policy)['source_role']])
    for url in ranked:
        if url in urls or not public_http(url):
            continue
        try:
            guard.check(url)
        except EgressBlocked:
            blocked += 1
            continue
        urls.append(url)
        if len(urls) == 3:
            break

    async def scrape(url):
        failure = None
        try:
            async with asyncio.timeout(175):
                html, inner, final_url = unpack_page(await fetch(url), url)
            guard.check(final_url)
            if not public_http(final_url):
                return {'url': url, 'error': 'destination_rejected', 'access_status': 'blocked'}
            status, reason = access_check(html, inner)
            if status != 'accessible':
                failure = {'url': url, 'error': reason, 'access_status': status}
            else:
                page = {'url': final_url, 'text': inner.strip()[:10000], 'access_status': 'accessible',
                        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'stale': False,
                        **authority(final_url, policy)}
                if cache is not None:
                    cache.put(url, page)
                return page
        except EgressBlocked:
            return {'url': url, 'error': 'destination_rejected', 'access_status': 'blocked'}
        except (TimeoutError, httpx.TimeoutException):
            failure = {'url': url, 'error': 'timeout', 'access_status': 'timeout'}
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            failure = {'url': url, 'error': 'page_unavailable', 'access_status': 'blocked' if code in (401, 403, 429) else 'timeout' if code == 504 else 'unavailable'}
        except Exception:
            failure = {'url': url, 'error': 'page_unavailable', 'access_status': 'unavailable'}
        old = cache.get(url) if cache is not None else None
        if old:
            guard.check(old['url'])
            return dict(old, access_status=failure['access_status'], access_error=failure['error'])
        return failure

    pages = await asyncio.gather(*(scrape(url) for url in urls))
    sources, errors, blocks, budget = [], [], [], 10000
    for index, page in enumerate(pages):
        if 'error' in page:
            errors.append(page)
            continue
        prefix = '[' + page['url'] + ']\n'
        allowance = max(0, budget // (len(pages) - index) - len(prefix) - 2)
        text = page['text'][:allowance]
        if not text:
            continue
        sources.append(dict(page, text=text))
        if page.get('stale'):
            errors.append({'url': page['url'], 'error': page['access_error'], 'access_status': page['access_status']})
        block = prefix + text
        blocks.append(block)
        budget -= len(block) + 2
    failures = {e.get('access_status', 'unavailable') for e in errors}
    return {'sources': sources, 'text': '\n\n'.join(blocks), 'errors': errors,
            'access_status': 'accessible' if sources and not errors else 'partial' if sources else next(iter(failures)) if len(failures) == 1 else 'unavailable',
            'blocked_urls': blocked}


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
            html, inner, final_url = unpack_page(await fetch(url), url)
            guard.check(final_url)
            status, reason = access_check(html, inner)
            if status != 'accessible':
                errors.append({'url': url, 'error': reason, 'access_status': status})
                continue
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


class LiveResearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


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


def create_app(guard=None, search=searxng_search, fetch=browser_fetch, verify=laya_verify, threshold=None,
               bnr_get=http_get):
    guard = guard or load()  # fail-closed: fără denylist validă, serviciul nu pornește
    threshold = threshold if threshold is not None else float(os.environ.get("LAYA_THRESHOLD", 0.9))
    app = FastAPI(title="research-gateway")
    from research_gateway.login import install_login
    install_login(app)
    from research_gateway.mail import router as mail_router
    app.include_router(mail_router(guard))
    policy, cache = load_policy(), PageCache()
    live_slots = asyncio.Semaphore(2)

    @app.post('/live-research')
    async def live_endpoint(body: LiveResearchIn):
        try:
            async with asyncio.timeout(200):
                async with live_slots:
                    return await live_research(body.query, guard=guard, search=search, fetch=fetch, policy=policy, cache=cache)
        except EgressBlocked as e:
            raise HTTPException(403, {'blocked': e.rules}) from None
        except (httpx.HTTPError, TimeoutError):
            raise HTTPException(502, 'Căutarea web nu este disponibilă.') from None

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
