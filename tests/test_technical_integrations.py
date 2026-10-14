from decimal import Decimal

import pytest

from app.rag.quantities import comparison_key, parse_quantity
from app.rag.rerank import rerank
from app.rag.evidence import contradictions, source_units
from app.rag.assessment import assess


@pytest.mark.parametrize('left,right,prop', [
    ('0,5 MPa', '5 bar', 'presiune'), ('12000 g', '12 kg', 'masa'),
    ('0.02 m', '20 mm', 'diametru'), ('20 °C', '293.15 K', 'temperatura'),
    ('80 N·m', '80 Nm', 'cuplu'),
])
def test_pint_equivalence_without_changing_original(left, right, prop):
    a, b = parse_quantity(left, prop), parse_quantity(right, prop)
    assert a and b
    assert a['original_value'] == left
    assert Decimal(a['value']) == Decimal(b['value'])
    assert comparison_key(left, prop) == comparison_key(right, prop)


@pytest.mark.parametrize('value,prop', [('12 mm', 'masa'), ('12 +/- 1 kg', 'masa'),
    ('10–12 kg', 'masa'), ('1.200,5 kg', 'masa'), ('1 mPa', 'presiune'), ('1 EUR', 'presiune'),
    ('__import__("os")', 'masa'), ('NaN kg', 'masa')])
def test_unsupported_or_ambiguous_quantities_not_guessed(value, prop):
    assert parse_quantity(value, prop) is None


def test_equivalent_pressures_not_conflicting_and_originals_retained():
    def fragment(doc, value):
        return {'doc_id': doc, 'page': 1, 'text': f'| Cod | Presiune |\n|---|---|\n| PART123 | {value} |'}
    units = source_units([fragment('a', '0,5 MPa'), fragment('b', '5 bar')], 'Presiune PART123?')
    assert not contradictions(units)
    claims = assess(units, [])['technical_claims']
    assert [c['value'] for c in claims] == ['0,5 MPa', '5 bar']
    assert claims[0]['normalized_quantity']['value'] == '500000'
    different = source_units([fragment('a', '0,5 MPa'), fragment('b', '6 bar')], 'Presiune PART123?')
    assert contradictions(different)


def test_reranking_preserves_full_sources_and_never_changes_values():
    candidates = [{'doc_id': 'a', 'text': 'PART123 120 kg'}, {'doc_id': 'b', 'text': 'PART123 12 kg', 'page': 7}]
    seen = []
    def scorer(pairs):
        seen.extend(pairs)
        return [0.1, 0.9]
    result, status = rerank('masa PART123', candidates, 1, scorer)
    assert status == 'applied' and result[0]['doc_id'] == 'b'
    assert result[0]['text'] == 'PART123 12 kg' and result[0]['page'] == 7
    assert len(seen) == 2 and 'rerank_score' not in candidates[1]


@pytest.mark.parametrize('scores', [[], [float('nan')], [0.1, 0.2]])
def test_invalid_reranker_scores_fall_back(scores):
    candidates = [{'text': 'original'}]
    assert rerank('q', candidates, 1, lambda p: scores) == (candidates, 'fallback')


def test_reranker_unavailable_and_scalar_score():
    candidates = [{'text': 'original'}]
    def fail(pairs):
        raise FileNotFoundError('private message')
    assert rerank('q', candidates, 1, fail) == (candidates, 'fallback')
    assert rerank('q', candidates, 1, lambda p: 0.9)[1] == 'applied'


def test_prose_pressure_retains_si_case():
    units = source_units([{'doc_id': 'a', 'page': 1, 'text': 'PART123 presiune 0,5 MPa.'},
                          {'doc_id': 'b', 'page': 1, 'text': 'PART123 presiune 5 bar.'}], 'presiune PART123')
    assert not contradictions(units)
    assert assess(units, [])['technical_claims'][0]['normalized_quantity']['value'] == '500000'


def test_missing_local_model_fails_before_import(monkeypatch, tmp_path):
    import app.rag.rerank as module
    monkeypatch.setattr(module, '_model', None)
    monkeypatch.setenv('RERANK_MODEL_PATH', str(tmp_path / 'missing'))
    with pytest.raises(FileNotFoundError):
        module.compute_scores([['q', 'p']])


def test_geometry_is_retained_for_audit_but_not_sent_to_model():
    import json
    from app.rag.evidence import selection_messages
    unit = {'id': 'abc', 'quote': '12 kg', 'provenance': [{'ref': 'large-geometry'}]}
    messages = selection_messages('masa?', [unit], '')
    assert json.loads(messages[1]['content'])['evidence'] == [{'id': 'abc', 'quote': '12 kg'}]
    assert unit['provenance']
