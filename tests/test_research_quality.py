import asyncio
import json

import pytest

from research_gateway.quality import access_check, authority
from research_gateway.app import PageCache, live_research
from research_gateway.egress_guard import EgressGuard
from app.rag.assessment import assess
from app.rag.evidence import source_units, contradictions
from scripts.inventory_suppliers import inventory


@pytest.mark.parametrize('html,text,status', [
    ('', 'Verify you are human', 'blocked'),
    ('', 'Checking your browser', 'blocked'),
    ('', 'Access denied', 'blocked'),
    ('', 'Sign in to continue', 'blocked'),
    ('<input type="password">', 'Portal', 'blocked'),
    ('', '', 'unavailable'),
    ('', 'PART123 masa 12 kg', 'accessible'),
])
def test_access_labeled_fixture(html, text, status):
    assert access_check(html, text)[0] == status


def unit(**changes):
    fragment = {'doc_id': 'https://maker.example/p', 'url': 'https://maker.example/p', 'page': 1,
                'text': 'Cod\tProducator\tVarianta\tRevizie\tConditii\tMasa\nPART123\tMaker\tA\t2\t20 C\t12 kg',
                'source_type': 'web', 'source_role': 'manufacturer', 'manufacturer': 'Maker',
                'publisher_group': 'maker', 'stale': False, **changes}
    return source_units([fragment], 'Masa PART123?')[0]


def test_complete_official_claim_and_traceability():
    result = assess([unit()], [])
    assert result['evidence_status'] == 'confirmed'
    claim = result['technical_claims'][0]
    assert claim['value'] == '12 kg' and claim['unit'] == 'kg'
    assert claim['identity']['variant'] == 'A' and claim['document_revision'] == '2'
    assert not result['automatic_offer_eligible'] and result['requires_human_review']


@pytest.mark.parametrize('changes,reason', [
    ({'stale': True}, 'historical_copy'),
    ({'source_role': 'secondary'}, 'source_authority_unreviewed'),
    ({'manufacturer': 'Other'}, 'manufacturer_mismatch'),
    ({'text': 'PART123 masa 12 kg.'}, 'incomplete_product_identity'),
])
def test_unconfirmed_reasons(changes, reason):
    result = assess([unit(**changes)], [])
    assert result['evidence_status'] == 'unconfirmed'
    assert reason in result['technical_claims'][0]['reasons']


def test_duplicate_distributor_copies_are_not_independent_confirmation():
    a = unit(source_role='authorized_distributor', publisher_group='a')
    b = unit(source_role='authorized_distributor', publisher_group='b', doc_id='https://other.example')
    assert assess([a, b], [])['evidence_status'] == 'unconfirmed'


def test_conflicting_values_never_confirmed():
    a = unit()
    b = unit(doc_id='https://other.example', text='Cod\tProducator\tVarianta\tRevizie\tConditii\tMasa\nPART123\tMaker\tA\t2\t20 C\t120 kg')
    result = assess([a, b], contradictions([a, b]))
    assert result['evidence_status'] == 'contradictory'
    assert all(c['evidence_status'] == 'contradictory' for c in result['technical_claims'])


def test_exact_model_suffix_does_not_match():
    assert source_units([{'doc_id': 'x', 'page': 1, 'text': 'PART123A masa 120 kg.'}], 'Masa PART123?') == []


def test_wrong_unit_dimension_and_missing_property_prevent_confirmation():
    bad = unit()
    bad['fields']['Masa'] = '12 mm'
    assert 'unit_dimension_mismatch' in assess([bad], [])['technical_claims'][0]['reasons']
    result = assess([unit()], [], 'Masa și lungimea PART123?')
    assert result['missing_properties'] == ['lungime']
    assert result['evidence_status'] == 'unconfirmed'


def test_official_priority_redirect_authority_and_stale_fallback():
    async def run():
        policy = {'maker.example': {'role': 'manufacturer', 'manufacturer': 'Maker', 'publisher_group': 'maker'}}
        assert authority('https://maker.example.evil.test', policy)['source_role'] == 'secondary'
        assert authority('https://sub.maker.example', policy)['source_role'] == 'secondary'
        async def search(q):
            return ['https://secondary.example', 'https://maker.example']
        seen = []
        blocked = False
        async def fetch(url):
            seen.append(url)
            return {'html': '', 'text': 'Verify you are human' if blocked else 'PART123 masa 12 kg', 'url': 'https://redirect.example'}
        cache = PageCache()
        args = dict(guard=EgressGuard(['SecretClient']), search=search, fetch=fetch, policy=policy, cache=cache)
        first = await live_research('PART123', **args)
        assert seen[0] == 'https://maker.example'
        assert first['sources'][0]['source_role'] == 'secondary'  # redirect cannot inherit trust
        blocked = True
        second = await live_research('PART123', **args)
        assert second['sources'][0]['stale']
        assert second['sources'][0]['retrieved_at'] == first['sources'][0]['retrieved_at']
        assert second['sources'][0]['access_status'] == 'blocked'
        assert second['access_status'] == 'partial'
        assert 'Verify you are human' not in second['text']
    asyncio.run(run())


def test_offline_supplier_inventory_never_grants_trust(tmp_path):
    (tmp_path / 'orders.csv').write_text('supplier,website\nMaker,https://maker.example\n', encoding='utf-8')
    (tmp_path / 'datasheet.pdf').write_bytes(b'fake test PDF')
    (tmp_path / 'bad.xml').write_text('<!DOCTYPE a><a/>', encoding='utf-8')
    result = inventory(tmp_path)
    assert result['candidates'] == [{'supplier': 'Maker', 'domain_candidate': 'maker.example', 'source_file': 'orders.csv', 'review_status': 'unreviewed'}]
    assert len(result['files_for_review']) == 2
    assert not list(tmp_path.glob('*policy*'))
