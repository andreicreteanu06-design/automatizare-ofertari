"""Project/owner-scoped review memory. Human notes never become source facts."""
import re

from app.rag.evidence import ALIASES, normalized
from app.rag.retrieve import code_candidates


def applicable(query, corrections):
    current = normalized(query)
    codes = set(code_candidates(query))
    properties = {p for p, aliases in ALIASES.items() if any(re.search(r'\b' + a + r'\w*', current) for a in aliases)}
    result = []
    for correction in corrections:
        prior = normalized(correction['query'])
        prior_codes = set(code_candidates(correction['query']))
        prior_props = {p for p, aliases in ALIASES.items() if any(re.search(r'\b' + a + r'\w*', prior) for a in aliases)}
        identical = re.sub(r'\W+', ' ', current).strip() == re.sub(r'\W+', ' ', prior).strip()
        related = codes and codes & prior_codes and properties and properties & prior_props
        if identical or related:
            result.append(correction)
    return result[:20]


def excluded(unit, reviews):
    # Match exact excerpts as well as IDs, so re-uploading identical text under a
    # different source ID cannot silently restore the same rejected answer.
    for review in reviews:
        for rejected in review['rejected_evidence']:
            if (unit['id'] == rejected['id'] or
                (normalized(unit['quote']) == normalized(rejected['quote']) and unit.get('fields') == rejected.get('fields'))):
                return True
    return False


def model_notes(reviews):
    # Bounded untrusted context, separate from the evidence allowed in answers.
    return [{'query': r['query'][:300], 'note': r['note'][:600]} for r in reviews[:5]]
