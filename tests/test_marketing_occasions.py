"""An editorial occasion never supplies exchange, popularity or causal facts."""
import json
from datetime import timedelta

import pytest

from marketing import agents, content, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401
from test_marketing_execution import model_clock  # noqa: F401
from test_marketing_production import ProductionModel, brief, run_team


def occasion(kind='holiday', **changes):
    original = evidence('occasion', **{'entity': '', 'title': 'Подтверждённый календарь' if kind == 'holiday' else 'Объявление разработчика игры',
        'data': {}, 'units': {}, 'excerpt': 'Подтверждена дата события в тестовом оригинале.', **changes})
    return {'kind': kind, 'evidence_id': original['id'], 'evidence_version': original['version']}


class OccasionModel(ProductionModel):
    def __init__(self, *, body=None):
        super().__init__()
        self.body = body

    def complete_json(self, system, user, **options):
        result = super().complete_json(system, user, **options)
        context = json.loads(user)
        for draft in result.get('drafts', []):
            kind = context['production']['occasion']['kind']
            titles = {'holiday': ('К празднику — спокойная проверка', 'Bayram oldidan xotirjam tekshiruv'),
                      'gaming': ('Одна свеча — не весь сюжет', 'Bitta sham — butun voqea emas')}
            bodies = {'holiday': ('Перед праздником проверьте дату отчёта и первоисточник. Праздник не подтверждает закрытие биржи.',
                                 'Bayram oldidan hisobot sanasi va birlamchi manbani tekshiring.'),
                      'gaming': ('Игровой сюжет — приём объяснения. Релиз не доказывает влияние на акции и не подтверждает популярность.',
                                 'O‘yin voqeasi tushuntirish usuli. Bu aksiya narxiga ta’sirni isbotlamaydi.')}
            draft.update(title=titles[kind][draft['language'] == 'uz'],
                body=self.body or bodies[kind][draft['language'] == 'uz'], evidence_ids=['occasion'], claims=[],
                destination_url=context['production']['destination_url'])
        return result


def start(ref, **changes):
    account(languages=['ru', 'uz'])
    return agents.start(OWNER, kind='content', message='Используйте подтверждённый повод без рыночных выдумок.',
        evidence_ids=['occasion'], production=brief(entity='', mode='account', occasion=ref,
            targets=[{'account_id': 'tg', 'languages': ['ru', 'uz'], 'primary_language': 'ru', 'format': 'post'}], **changes))


@pytest.mark.parametrize('kind', ['holiday', 'gaming'])
def test_confirmed_occasion_is_pinned_through_all_roles_and_distinct_language_drafts(kind):
    ref = occasion(kind)
    task = start(ref)
    model = OccasionModel()
    run_team(model)
    with store.connection() as c:
        item, = store.list_items(c, 'candidate')
        variants = store.list_items(c, 'draft_variant')
        assert store.list_items(c, 'delivery') == []
    assert item['status'] == 'ready', item['check']
    assert item['occasion'] == task['production']['occasion'] == ref
    assert len(variants) == 2 and {row['language'] for row in variants} == {'ru', 'uz'}
    assert all(context['production']['occasion'] == ref for _, context in model.calls)
    assert all('exchange schedule' in system and 'gaming' in system for system, _ in model.calls)
    assert ('праздник' in item['title'].lower()) == (kind == 'holiday')


@pytest.mark.parametrize('kind,language,body,risk', [
    ('holiday', 'ru', 'В праздник биржа закрыта.', 'exchange schedule'),
    ('holiday', 'en', 'The exchange is closed for the holiday.', 'exchange schedule'),
    ('holiday', 'uz', 'Bayram kuni birja yopiq.', 'exchange schedule'),
    ('gaming', 'ru', 'Популярная игра: её все обсуждают.', 'popularity'),
    ('gaming', 'en', 'Everyone is playing this popular game.', 'popularity'),
    ('gaming', 'uz', 'Bu mashhur o‘yinni hamma muhokama qilmoqda.', 'popularity'),
    ('gaming', 'ru', 'Релиз игры вызвал рост акций.', 'market effect'),
    ('gaming', 'en', 'The game release caused share prices to rise.', 'market effect'),
    ('gaming', 'uz', 'O‘yin relizi aksiya narxiga ta’sir qildi.', 'market effect'),
    ('gaming', 'ru', 'Релиз не подтверждает популярность, но игру все обсуждают.', 'popularity'),
])
def test_editorial_event_does_not_authorize_unsupported_operational_popularity_or_market_claims(kind, language, body, risk):
    ref = occasion(kind)
    account(languages=[language])
    item = candidate('occasion-release', entity='', title='UZStock', body=body, language=language,
                     evidence_ids=['occasion'], claims=[], occasion=ref)
    result = content.check_candidate(item['id'], NOW)
    assert result['status'] == 'skipped' and risk in result['check']['reason']
    assert content.create_candidate({key: item[key] for key in content.Candidate.model_fields})['status'] == 'skipped'
    with store.connection() as c:
        assert store.list_items(c, 'delivery') == []


def test_exact_checked_statement_can_support_a_schedule_but_not_an_extra_unchecked_claim():
    statement = 'Биржа закрыта в праздничный день.'
    ref = occasion(excerpt=statement, data={'exchange_schedule': statement})
    account(mode='manual')
    item = candidate('confirmed-schedule', entity='', title='Проверенный календарь', body=statement,
        evidence_ids=['occasion'], occasion=ref, mode='manual',
        claims=[{'evidence_id': 'occasion', 'field': 'exchange_schedule', 'value': statement, 'unit': ''}])
    result = content.check_candidate(item['id'], NOW)
    assert result['status'] == 'awaiting_approval', result['check']
    approved = content.approve_candidate(OWNER, item['id'], result['version'])
    changed = content.revise_candidate(OWNER, item['id'], {'body': statement + ' Торги начнутся утром.'}, approved['version'])
    assert changed['approval'] is None
    assert content.check_candidate(item['id'], NOW)['status'] == 'needs_revision'


@pytest.mark.parametrize('changes', [
    {'status': 'candidate'}, {'event_at': None}, {'rights': 'unknown'},
    {'expires_at': (NOW - timedelta(minutes=1)).isoformat()},
])
def test_an_occasion_needs_a_verified_dated_available_original_before_model_work(changes):
    ref = occasion(**changes)
    with pytest.raises(MarketingError, match='occasion'):
        start(ref)
    with store.connection() as c:
        assert store.list_items(c, 'task') == []


def test_changed_occasion_during_a_role_call_blocks_that_result_without_losing_earlier_handoffs():
    ref = occasion()
    task = start(ref)
    agents.run_one(OccasionModel(), NOW)
    class ChangedOriginal(OccasionModel):
        def complete_json(self, *args, **kwargs):
            with store.connection() as c:
                original = store.get(c, 'evidence', 'occasion')
            content.save_evidence(OWNER, 'occasion', {**{key: original[key] for key in content.Evidence.model_fields},
                'event_at': (NOW + timedelta(days=3)).isoformat()}, original['version'])
            return super().complete_json(*args, **kwargs)
    agents.run_one(ChangedOriginal(), NOW)
    with store.connection() as c:
        current = store.get(c, 'task', task['id'])
        assert current['status'] == 'blocked' and 'occasion' in current['reason']
        assert len(current['outputs']) == 1
        assert store.list_items(c, 'candidate') == []
