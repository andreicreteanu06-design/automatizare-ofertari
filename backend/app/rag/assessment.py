"""Evidence confidence is separate from verbatim extraction and page access."""
import hashlib
import re
from app.rag.quantities import parse_quantity, comparison_key, scalar_from_prose


def assess(units, conflicts, query=''):
    from app.rag.evidence import ALIASES, normalized
    claims = []
    for u in units:
        fields = {normalized(k): v for k, v in u['fields'].items()}
        def field(*keys):
            return next((fields[k] for k in keys if fields.get(k)), None)
        identity = {'manufacturer': field('producator', 'manufacturer', 'brand'),
                    'variant': field('varianta', 'variant', 'model'),
                    'revision': field('revizie', 'revision', 'rev'),
                    'codes': u['codes']}
        conditions = field('conditii', 'conditions', 'test conditions')
        product_code = field('cod', 'code', 'sku', 'mpn', 'cod produs', 'product code')
        for prop in u['properties']:
            value = next((v for k, v in fields.items() if any(a == k or k.startswith(a + ' ') for a in ALIASES[prop])), None)
            if value is None:
                value = scalar_from_prose(u['quote'], ALIASES[prop])
            if value is None:
                continue
            measure = re.fullmatch(r'\s*([-+]?\d+(?:[.,]\d+)?)\s*(kg|g|mm|cm|m|bar|mpa|pa|°c|eur|ron|usd)\s*', value, re.I)
            reasons = []
            canonical = parse_quantity(value, prop)
            if not product_code or product_code.upper() not in u['codes']:
                reasons.append('exact_product_code_unconfirmed')
            if not identity['codes'] or not all(identity[k] for k in ('manufacturer', 'variant', 'revision')):
                reasons.append('incomplete_product_identity')
            if (prop not in ('material', 'pret') and not canonical) or (prop == 'pret' and not measure):
                reasons.append('missing_or_ambiguous_unit')
            dimensions = {'masa': {'kg', 'g'}, 'lungime': {'m', 'cm', 'mm'}, 'latime': {'m', 'cm', 'mm'},
                          'inaltime': {'m', 'cm', 'mm'}, 'diametru': {'m', 'cm', 'mm'},
                          'presiune': {'bar', 'mpa', 'pa'}, 'temperatura': {'°c'}, 'pret': {'eur', 'ron', 'usd'}}
            if measure and not canonical and measure[2].lower() not in dimensions.get(prop, set()):
                reasons.append('unit_dimension_mismatch')
            if not conditions:
                reasons.append('measurement_conditions_missing')
            if u.get('stale'):
                reasons.append('historical_copy')
            trusted = u.get('source_role') in ('manufacturer', 'authorized_distributor')
            if not trusted:
                reasons.append('source_authority_unreviewed')
            if trusted and normalized(identity['manufacturer'] or '') != normalized(u.get('manufacturer') or ''):
                reasons.append('manufacturer_mismatch')
            claims.append({'evidence_id': u['id'], 'identity': identity, 'property': prop,
                           'value': value, 'unit': canonical['original_unit'] if canonical else measure[2] if measure else None,
                           'normalized_quantity': canonical, 'conditions': conditions,
                           'quote': u['quote'], 'url': u.get('url'), 'doc_id': u['doc_id'],
                           'retrieved_at': u.get('retrieved_at'), 'document_revision': identity['revision'],
                           'source_role': u.get('source_role', 'internal_unreviewed'),
                           'publisher_group': u.get('publisher_group'),
                           'content_fingerprint': hashlib.sha256(normalized(u['quote']).encode()).hexdigest(),
                           'reasons': reasons, 'evidence_status': 'unconfirmed'})
    for claim in claims:
        if any(c['property'] == claim['property'] and c['code'] in claim['identity']['codes'] for c in conflicts):
            claim['evidence_status'] = 'contradictory'
            claim['reasons'].append('conflicting_values')
            continue
        if claim['reasons']:
            continue
        peers = [c for c in claims if not c['reasons'] and c['identity'] == claim['identity']
                 and c['property'] == claim['property'] and comparison_key(c['value'], c['property']) == comparison_key(claim['value'], claim['property'])
                 and c['conditions'] == claim['conditions']]
        independent = len({c['publisher_group'] for c in peers}) > 1 and len({c['content_fingerprint'] for c in peers}) > 1
        if claim['source_role'] == 'manufacturer' or independent:
            claim['evidence_status'] = 'confirmed'
        else:
            claim['reasons'].append('independent_confirmation_missing')
    requested = {p for p, aliases in ALIASES.items() if any(re.search(r'\b' + a + r'\w*', normalized(query)) for a in aliases)}
    missing = sorted(requested - {c['property'] for c in claims})
    status = ('contradictory' if conflicts else 'confirmed' if claims and not missing and all(c['evidence_status'] == 'confirmed' for c in claims)
              and {c['evidence_id'] for c in claims} == {u['id'] for u in units} else 'unconfirmed')
    return {'evidence_status': status, 'technical_claims': claims, 'missing_properties': missing,
            'automatic_offer_eligible': False, 'requires_human_review': True}
