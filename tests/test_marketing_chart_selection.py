"""Chart preparation pins a chosen original series through the real role/render flow."""
import json

import pytest

from marketing import agents, automation, content, media, production, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, account, evidence, isolated  # noqa: F401
from test_marketing_execution import model_clock  # noqa: F401
from test_marketing_automation import setup_rule, verified, rows, update_rule
from test_marketing_agents import output
from test_marketing_production import brief, ProductionModel

SERIES = [{'date': '2026-11-19', 'value': 120}, {'date': '2026-11-20', 'value': 100}]


def chart_rule(**changes):
    return setup_rule(allowed_rubrics=['chart'], formats=['image'], languages=['ru', 'uz'],
                      rubric='chart', chart_field='close',
                      target={'account_id': 'tg', 'languages': ['ru', 'uz'], 'primary_language': 'ru', 'format': 'image'}, **changes)


def original(key='chart-original', **changes):
    return verified(key, **{'canonical_event_id': 'hmkb-prices-2026-11-20', 'suggested_rubric': 'chart',
        'url': 'https://market.test/HMKB/history',
        'title': 'Цены HMKB', 'period': '2026-11-20', 'excerpt': 'Подтверждённые цены закрытия за указанные даты.',
        'data': {'close': SERIES, 'turnover': [{'date': p['date'], 'value': 5000} for p in SERIES]},
        'units': {'close': 'UZS/share', 'turnover': 'UZS'},
        'destination_url': 'https://uzstock.uz/company/HMKB#chart', **changes})


class ChartModel(ProductionModel):
    def __init__(self, *, omit_source=False):
        super().__init__()
        self.omit_source = omit_source

    def complete_json(self, system, user, **options):
        context = json.loads(user)
        if "You are UZStock's copywriter " not in system:
            return super().complete_json(system, user, **options)
        self.calls.append((system, context))
        source = context['production']['chart']['evidence_id']
        return output('Варианты вопроса и пояснения готовы', drafts=[{
            'account_id': target['account_id'], 'language': language,
            'title': 'Как менялась цена?' if language == 'ru' else 'Narx qanday o‘zgardi?',
            'body': 'Цена за выбранные даты, без прогноза.' if language == 'ru' else 'Tanlangan sanalardagi narx, prognozsiz.',
            'evidence_ids': [row['id'] for row in context['evidence'] if not self.omit_source or row['id'] != source],
            'claims': [], 'destination_url': context['production']['destination_url'], 'founder_fact_ids': [],
        } for target in context['production']['targets'] for language in target['languages']])


def finish(task, model):
    for _ in range(20):
        agents.run_one(model, NOW)
        while media.run_one(NOW):
            pass
        with store.connection() as c:
            current = store.get(c, 'task', task['id'])
        if current['status'] == 'complete':
            return current
    pytest.fail(f"Chart production did not finish: {current['status']} {current['reason']}")


def test_rule_selects_its_exact_series_renders_both_languages_and_preserves_one_draft():
    rule = chart_rule()
    ev = original()
    assert automation.run_one(NOW)
    task, = rows('task')
    assert task['production']['chart'] == {'evidence_id': ev['id'], 'field': 'close'}
    assert task['production']['destination_url'] == ev['destination_url']
    model = ChartModel()
    saved = finish(task, model)
    item, = rows('candidate')
    assert item['status'] == 'draft' and item['check']['passed']
    assert len(rows('draft_variant')) == 2 and len(rows('asset')) == 2
    assert all(asset['chart']['series'] == SERIES and asset['chart']['unit'] == 'UZS/share' for asset in rows('asset'))
    assert saved['candidate_ids'] == [item['id']]
    assert model.calls[0][1]['production']['chart']['field'] == 'close'
    uz = next(row for row in rows('draft_variant') if row['language'] == 'uz')
    selected = production.select_variant(OWNER, uz['id'], item['version'], now=NOW)
    assert selected['id'] == item['id'] and selected['check']['passed']
    assert selected['language'] == 'uz'
    assert not automation.run_one(NOW)
    assert rows('delivery') == []
    assert update_rule(rule, enabled=False)['chart_field'] == 'close'


@pytest.mark.parametrize('case', ['missing', 'unit', 'future', 'reversed', 'conflict'])
def test_automatic_chart_selection_waits_for_one_usable_unambiguous_original(case):
    chart_rule()
    if case == 'missing':
        original(data={'turnover': SERIES}, units={'turnover': 'UZS'})
    elif case == 'unit':
        original(units={'close': ''})
    elif case == 'future':
        original(data={'close': [SERIES[0], {'date': '2026-12-01', 'value': 100}]})
    elif case == 'reversed':
        original(data={'close': list(reversed(SERIES))})
    else:
        original()
        original('conflicting-reprint', url='https://media.test/chart-copy', data={'close': [SERIES[0], {'date': SERIES[1]['date'], 'value': 200}]})
    assert not automation.run_one(NOW)
    assert rows('task') == [] and rows('candidate') == [] and rows('render') == []


@pytest.mark.parametrize('change', ['post', 'missing_field', 'irrelevant_field'])
def test_chart_selection_contract_cannot_silently_fall_back_to_a_plain_post(change):
    from pydantic import ValidationError
    rule = chart_rule(enabled=False)
    value = {'chart_field': ''} if change == 'missing_field' else {'rubric': 'news'} if change == 'irrelevant_field' else {
        'target': {**rule['target'], 'format': 'post'}}
    with pytest.raises(ValidationError):
        update_rule(rule, **value)


@pytest.mark.parametrize('case', ['unselected', 'missing_field', 'wrong_format'])
def test_owner_chart_brief_validates_the_original_before_creating_any_task(case):
    from pydantic import ValidationError
    account('telegram', formats=['image'], rubrics=['chart'])
    evidence('prices', data={'close': SERIES}, units={'close': 'UZS/share'})
    evidence('other', data={'close': SERIES}, units={'close': 'UZS/share'})
    scope = brief(rubric='chart', chart={'evidence_id': 'other' if case == 'unselected' else 'prices',
                                       'field': 'missing' if case == 'missing_field' else 'close'},
                  targets=[{'account_id': 'telegram', 'languages': ['ru'], 'primary_language': 'ru', 'format': 'post' if case == 'wrong_format' else 'image'}])
    with pytest.raises((MarketingError, ValidationError)):
        agents.start(OWNER, kind='content', message='Подготовить график', evidence_ids=['prices'], production=scope)
    assert rows('task') == []


def test_copywriter_cannot_drop_the_pinned_series_from_its_selected_originals():
    chart_rule()
    original()
    original('context-only', url='https://media.test/background', data={'background': 'История торгов'}, units={})
    assert automation.run_one(NOW)
    model = ChartModel(omit_source=True)
    task, = rows('task')
    for _ in range(6):
        agents.run_one(model, NOW)
    current = next(row for row in rows('task') if row['id'] == task['id'])
    assert current['status'] == 'error'
    assert rows('candidate') == [] and rows('asset') == []
