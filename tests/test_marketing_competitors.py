"""Competitor comparisons retain dated observations and undisclosed metrics."""
import pytest

from marketing import agents, store
from test_marketing_agents import Model, output
from test_marketing_core import OWNER, NOW, evidence, isolated  # noqa: F401

FIELDS = ('purpose', 'audience', 'features', 'pricing', 'communication', 'revenue', 'conversion', 'audience_size')


def comparison(**changes):
    return {'product': 'Local example', 'relationship': 'direct', 'relationship_reason': 'Serves the same investor task.',
            'difference_hypothesis': 'Test whether clearer report explanations help our audience.',
            'facts': [{'field': field, 'evidence_id': 'competitor' if field in {'features', 'pricing'} else '',
                       'observed_excerpt': {'features': 'Issuer charts and saved lists.', 'pricing': 'A monthly plan costs 100 units.'}.get(field, '')}
                      for field in FIELDS], **changes}


def setup():
    evidence('competitor', title='Dated competitor extract', entity='Local example', data={}, units={},
             excerpt='Issuer charts and saved lists. A monthly plan costs 100 units.')
    evidence('inspiration', title='International example extract', entity='International inspiration', data={}, units={},
             excerpt='Issuer charts and saved lists. A monthly plan costs 100 units.')
    return agents.start(OWNER, kind='competitors', message='Compare disclosed features and prices without inventing sales.', evidence_ids=['competitor', 'inspiration'])


def saved(task):
    with store.connection() as c:
        return store.get(c, 'task', task['id'])


def test_comparison_keeps_disclosed_snapshot_and_unknown_metrics_distinct_and_reaches_cmo():
    task = setup()
    assert task['steps'] == ['market', 'cmo']
    international = comparison(product='International inspiration', relationship='inspiration')
    for fact in international['facts']:
        if fact['evidence_id']:
            fact['evidence_id'] = 'inspiration'
    model = Model([output('Two different comparison roles.', competitor_cards=[comparison(), international]),
                   output('Use this as a positioning hypothesis, not a revenue ranking.')])
    agents.run_one(model, NOW)
    agents.run_one(model, NOW)
    result = saved(task)
    assert result['status'] == 'complete'
    cards = result['outputs'][0]['result']['competitor_cards']
    assert [row['relationship'] for row in cards] == ['direct', 'inspiration']
    facts = {row['field']: row for row in cards[0]['facts']}
    assert facts['pricing']['source']['version'] == 1
    assert facts['pricing']['source']['retrieved_at'] == '2026-11-23T07:00:00Z'
    assert facts['pricing']['observed_excerpt'] == 'A monthly plan costs 100 units.'
    for field in ('revenue', 'conversion', 'audience_size'):
        assert facts[field]['source'] is None
        assert facts[field]['observed_excerpt'] == ''
    assert model.calls[1][1]['outputs'][0]['result']['competitor_cards'] == cards
    with store.connection() as c:
        assert store.list_items(c, 'delivery') == []


@pytest.mark.parametrize('change', ['invented_quote', 'unselected_source', 'duplicate_field', 'missing_field', 'wrong_product'])
def test_competitor_facts_cannot_omit_unknown_fields_or_invent_observations(change):
    task = setup()
    card = comparison()
    if change == 'invented_quote':
        card['facts'][5].update(evidence_id='competitor', observed_excerpt='Revenue is 9000000.')
    elif change == 'unselected_source':
        card['facts'][3]['evidence_id'] = 'unselected'
    elif change == 'duplicate_field':
        card['facts'][-1] = card['facts'][0]
    elif change == 'wrong_product':
        card['facts'][3]['evidence_id'] = 'inspiration'
    else:
        card['facts'].pop()
    agents.run_one(Model([output('Comparison.', competitor_cards=[card])]), NOW)
    assert saved(task)['status'] == 'error'


def test_accepted_competitor_task_requires_structured_comparison():
    task = setup()
    agents.run_one(Model([output('All competitors are worse.')]), NOW)
    assert saved(task)['status'] == 'error'
