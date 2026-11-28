"""Inspectable format references cite only the material actually supplied."""
from datetime import timedelta

import pytest

from marketing import agents, content, sources, store
from test_marketing_agents import Model, output
from test_marketing_core import OWNER, NOW, evidence, isolated  # noqa: F401
from test_marketing_sources import article, source_input


def card(**changes):
    return {'evidence_id': 'format', 'recommendation': 'adapt',
            'observed_excerpt': 'One chart per card, followed by a source link.',
            'technique': 'One question and one chart per card.',
            'rationale': 'A focused sequence can explain a quarterly change.',
            'test_plan': 'Compare report arrivals for comparable topics; treat a small sample as preliminary.', **changes}


def source(**changes):
    return evidence('format', title='International format example', entity='', data={}, units={},
                    excerpt='First ask a question. One chart per card, followed by a source link.', **changes)


def research_task():
    task = agents.start(OWNER, kind='research', message='Find a reusable explanatory format', evidence_ids=['format'])
    agents.run_one(Model([output('Only the supplied excerpt is available.')]), NOW)
    return task


def saved(task):
    with store.connection() as c:
        return store.get(c, 'task', task['id'])


def test_reference_is_bound_to_the_selected_original_and_reaches_cmo_without_reuse_rights():
    original = source()
    task = research_task()
    model = Model([output('Adapt the structure, create original artwork.', reference_cards=[card()]), output('Test this format with a sourced report.')])
    agents.run_one(model, NOW)
    agents.run_one(model, NOW)
    item = saved(task)
    assert item['status'] == 'complete'
    selected = item['outputs'][1]['result']['reference_cards'][0]
    assert selected['source']['id'] == original['id']
    assert selected['source']['version'] == original['version']
    assert selected['source']['url'] == original['url']
    assert selected['source']['published_at'] == original['published_at']
    assert selected['source']['retrieved_at'] == original['retrieved_at']
    assert selected['source']['rights'] == 'link_and_excerpt'
    assert selected['source']['access'] == 'excerpt'
    assert model.calls[1][1]['outputs'][1]['result']['reference_cards'] == [selected]
    with store.connection() as c:
        assert store.list_items(c, 'delivery') == []


@pytest.mark.parametrize('changes', [
    {'status': 'unavailable'}, {'status': 'candidate'}, {'status': 'disabled'},
    {'rights': 'unknown'}, {'expires_at': (NOW-timedelta(minutes=1)).isoformat()},
])
def test_unavailable_or_unverified_reference_cannot_be_claimed_as_observed(changes):
    source(**changes)
    task = research_task()
    agents.run_one(Model([output('I observed this.', reference_cards=[card()])]), NOW)
    item = saved(task)
    assert item['status'] == 'error'
    assert len(item['outputs']) == 1


@pytest.mark.parametrize('changes', [
    {'evidence_id': 'not-selected'},
    {'observed_excerpt': 'The video opens with a drone shot.'},
    {'url': 'https://invented.example/video'},
])
def test_reference_cannot_invent_a_source_quote_or_address(changes):
    source()
    task = research_task()
    agents.run_one(Model([output('Reference analysis.', reference_cards=[card(**changes)])]), NOW)
    assert saved(task)['status'] == 'error'


def test_unavailable_reference_can_be_rejected_and_an_original_format_continues():
    source(status='unavailable')
    task = research_task()
    cards = [card(recommendation='reject', observed_excerpt='', technique='Not assessed: source unavailable.'),
             card(evidence_id='', recommendation='original', observed_excerpt='', technique='Our own question / chart / implication sequence.')]
    model = Model([output('No available reference; propose our own format.', reference_cards=cards), output('Proceed with an original draft.')])
    agents.run_one(model, NOW)
    agents.run_one(model, NOW)
    item = saved(task)
    assert item['status'] == 'complete'
    actual = item['outputs'][1]['result']['reference_cards']
    assert actual[0]['source']['access'] == 'unavailable'
    assert actual[1]['source'] is None


def test_research_acceptance_requires_inspectable_media_output_or_a_blocked_result():
    source()
    task = research_task()
    agents.run_one(Model([output('Everything looked good.')]), NOW)
    assert saved(task)['status'] == 'error'


def test_reference_source_change_is_detected_before_the_analysis_is_accepted():
    original = source()
    task = research_task()
    content.save_evidence(OWNER, 'format', {**{key: original[key] for key in content.Evidence.model_fields},
                                         'status': 'disabled'}, original['version'])
    agents.run_one(Model([output('Adapt it.', reference_cards=[card()])]), NOW)
    assert saved(task)['status'] == 'error'


def test_revoked_registry_permission_blocks_adaptation_even_when_evidence_version_is_unchanged():
    source_record = sources.save_source(OWNER, 'examples', source_input(method='manual'), 0)
    sources.import_materials(OWNER, source_record['id'], [article(excerpt=card()['observed_excerpt'])], NOW)
    with store.connection() as c:
        original = store.list_items(c, 'evidence')[0]
        registered = store.get(c, 'source', source_record['id'])
    sources.verify_evidence(OWNER, original['id'], original['version'], 'Compared the provided excerpt with its original.')
    task = agents.start(OWNER, kind='research', message='Assess this selected example.', evidence_ids=[original['id']])
    agents.run_one(Model([output('Review selected excerpt only.')]), NOW)
    sources.enable_source(OWNER, registered['id'], registered['version'], False)
    agents.run_one(Model([output('Adapt.', reference_cards=[card(evidence_id=original['id'])])]), NOW)
    assert saved(task)['status'] == 'error'
