"""Isolated Camoufox page fetcher. No cookies or browsing profiles are persisted."""
import asyncio
import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from stealth_browser.network import PublicProxy, public_url

app = FastAPI(title='stealth-browser')
# Browser memory is expensive. Gateway can schedule three pages concurrently;
# this service serializes actual browser instances within its 1.5 GiB budget.
slots = asyncio.Semaphore(1)


class FetchIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


async def check_guard(client, url):
    if not public_url(url):
        return False
    response = await client.post(os.environ.get('GUARD_URL', 'http://research-gateway:8000/guard/check'), json={'texts': [url]})
    response.raise_for_status()
    return response.json().get('ok') is True


async def fetch_page(url):
    from camoufox.async_api import AsyncCamoufox
    async with httpx.AsyncClient(timeout=5, trust_env=False) as guard_client:
        if not await check_guard(guard_client, url):
            raise HTTPException(403, 'Destinație respinsă de politica de acces.')
        async with PublicProxy() as proxy:
            async with AsyncCamoufox(headless=True, proxy={'server': proxy.url},
                                     firefox_user_prefs={'network.proxy.no_proxies_on': '',
                                                        'network.proxy.allow_hijacking_localhost': True,
                                                        'media.peerconnection.enabled': False,
                                                        'network.websocket.enabled': False}) as browser:
                context = await browser.new_context(service_workers='block', accept_downloads=False)
                checked = {}
                async def gate(route):
                    request = route.request
                    try:
                        if request.method not in ('GET', 'HEAD') or request.resource_type in ('image', 'media', 'font'):
                            return await route.abort()
                        if request.url not in checked:
                            checked[request.url] = await check_guard(guard_client, request.url)
                        if not checked[request.url]:
                            return await route.abort()
                        await route.continue_()
                    except (httpx.HTTPError, ValueError):
                        await route.abort()
                await context.route('**/*', gate)
                page = await context.new_page()
                response = await page.goto(url, wait_until='domcontentloaded', timeout=35000)
                if response and response.status >= 400:
                    raise HTTPException(502, 'Site-ul a refuzat accesul sau nu este disponibil.')
                # Late-rendered text gets a short bounded opportunity, never an endless networkidle wait.
                await page.wait_for_timeout(1500)
                if not await check_guard(guard_client, page.url):
                    raise HTTPException(403, 'Redirecționare respinsă.')
                html = await page.content()
                text = await page.evaluate('document.body ? document.body.innerText : ""')
                return {'url': page.url, 'html': html[:2_000_000], 'text': text[:100_000]}


@app.post('/fetch')
async def fetch(body: FetchIn):
    if not public_url(body.url):
        raise HTTPException(403, 'Sunt permise numai destinații HTTP(S) publice pe porturile 80/443.')
    try:
        async with asyncio.timeout(160):
            async with slots:
                async with asyncio.timeout(50):
                    return await fetch_page(body.url)
    except TimeoutError:
        raise HTTPException(504, 'Pagina nu a putut fi încărcată în timpul disponibil.') from None
    except HTTPException:
        raise
    except Exception as e:
        # Never return browser traces containing redirects or sensitive query strings.
        if type(e).__name__ == 'TimeoutError':
            raise HTTPException(504, 'Navigarea a expirat.') from None
        raise HTTPException(502, 'Browserul sau verificarea destinației nu este disponibilă.') from None


@app.get('/health')
def health():
    return {'ok': True}
