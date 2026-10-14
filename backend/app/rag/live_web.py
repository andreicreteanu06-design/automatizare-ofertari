"""Only the current explicitly opted-in question leaves the backend."""
import hashlib
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException


async def fetch_live(query):
    try:
        async with httpx.AsyncClient(timeout=210, trust_env=False) as client:
            response = await client.post(os.environ['RESEARCH_GATEWAY_URL'].rstrip('/') + '/live-research', json={'query': query})
            if response.status_code == 403:
                raise HTTPException(403, 'Căutarea web a fost blocată de Egress Guard. Elimină datele interne din întrebare.')
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('sources'), list):
            raise ValueError('invalid research response')
        fragments, remaining = [], 10000
        for source in data.get('sources', [])[:3]:
            if not isinstance(source, dict) or not isinstance(source.get('url'), str):
                raise ValueError('invalid web source')
            url, text = source['url'], source['text']
            parsed = urlsplit(url)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                    or parsed.password or len(url) > 2048 or not isinstance(text, str)):
                raise ValueError('invalid web source')
            text = text[:remaining]
            remaining -= len(text)
            fragments.append({'doc_id': url, 'page': 1, 'page_end': 1, 'text': text,
                              'source_type': 'web', 'url': url, 'supplier': parsed.hostname,
                              'source_role': source.get('source_role', 'secondary'),
                              'manufacturer': source.get('manufacturer'), 'publisher_group': source.get('publisher_group', parsed.hostname),
                              'stale': source.get('stale', False), 'access_status': source.get('access_status', 'accessible'),
                              'doc_type': 'Pagină web', 'source_revision': hashlib.sha256(text.encode()).hexdigest(),
                              'retrieved_at': source.get('retrieved_at', datetime.now(timezone.utc).isoformat())})
        return fragments, {'sources': [f['url'] for f in fragments], 'errors': data.get('errors', []),
                           'access_status': data.get('access_status', 'unavailable'),
                           'pages': [{k: f.get(k) for k in ('url', 'access_status', 'stale', 'retrieved_at', 'source_role')} for f in fragments],
                           'blocked_urls': data.get('blocked_urls', 0)}
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, 'Serviciul Live Web nu este disponibil sau a returnat un răspuns invalid.') from None
