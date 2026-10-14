"""Conservative access classification and locally administered source authority."""
import json
import os
import re
from urllib.parse import urlsplit


def access_check(html, text):
    visible = text.casefold()
    # Detect interstitials, including successful HTTP responses with challenge bodies.
    patterns = {
        'captcha': r'(verify (?:that )?you are human|complete the captcha|security verification|verifică dacă ești om)',
        'challenge': r'(checking your browser|just a moment|enable javascript and cookies to continue|unusual traffic)',
        'access_denied': r'(access denied|you have been blocked|request blocked)',
        'login_required': r'(sign in to continue|log in to continue|authentication required)',
    }
    for reason, pattern in patterns.items():
        if re.search(pattern, visible):
            return 'blocked', reason
    if re.search(r'<input\b[^>]*type\s*=\s*[\"\']password', html, re.I):
        return 'blocked', 'login_required'
    if not text.strip():
        return 'unavailable', 'empty_page'
    return 'accessible', None


def load_policy():
    path = os.environ.get('SOURCE_POLICY_PATH')
    if not path:
        return {}
    with open(path, encoding='utf-8') as stream:
        data = json.load(stream)
    domains = data['domains']
    if not isinstance(domains, dict):
        raise ValueError('Invalid source policy')
    for domain, record in domains.items():
        if (domain != domain.lower() or '/' in domain or ':' in domain or '.' not in domain
                or record.get('role') not in ('manufacturer', 'authorized_distributor')
                or not record.get('manufacturer') or not record.get('publisher_group')):
            raise ValueError('Invalid source authority record')
    return domains


def authority(url, policy):
    # Exact host only: no implicit trust for subdomains or matching substrings.
    host = (urlsplit(url).hostname or '').lower()
    record = policy.get(host, {})
    return {'source_role': record.get('role', 'secondary'),
            'manufacturer': record.get('manufacturer'),
            'publisher_group': record.get('publisher_group', host)}
