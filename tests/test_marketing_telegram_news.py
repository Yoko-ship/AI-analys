"""A Telegram channel needs no campaign setup to prepare its next news post."""
from datetime import timedelta

import pytest

from marketing import channels, permissions, sources, store
from test_marketing_channels import TelegramPeer
from test_marketing_core import OWNER, NOW, account, isolated  # noqa: F401
from test_marketing_execution import model_clock  # noqa: F401
from test_marketing_sources import article


def rows(kind):
    with store.connection() as c:
        return store.list_items(c, kind)


def connected(monkeypatch, **changes):
    TelegramPeer(monkeypatch)
    saved = account(**{'automatic_news': True, **changes})
    return channels.probe(OWNER, saved['id'], saved['version'], NOW)


def material(key='10523', **changes):
    return article(key, **{'canonical_event_id': 'news:' + key,
                   'url': 'https://www.uzdaily.uz/ru/sp-povysilo-reiting-uzbekneftegaza-do-bb',
                   'publisher': 'UzDaily.uz', 'event_at': None, 'data': {}, 'units': {},
                   **changes},
                   title='S&P повысило рейтинг «Узбекнефтегаза» до BB',
                   entity='UZNGP', excerpt='S&P повысило рейтинг с BB- до BB.',
                   destination_url='https://uzstock.uz/news/' + key)


def test_connected_telegram_prepares_news_without_goal_strategy_or_editorial_rule(monkeypatch):
    from marketing import telegram_news
    saved = connected(monkeypatch)
    assert telegram_news.ensure_source(NOW)
    source, = rows('source')
    assert source['enabled'] and source['method'] == 'internal_news'
    sources.import_materials(OWNER, source['id'], [material()], now=NOW)
    original, = rows('evidence')
    sources.verify_evidence(OWNER, original['id'], original['version'], 'Compared with the publisher')
    assert telegram_news.run_one(NOW)
    task, = rows('task')
    assert task['goal'] is None and rows('strategy') == [] and rows('editorial_rule') == []
    assert task['production']['targets'] == [{'account_id': saved['id'], 'languages': ['ru'],
                                             'primary_language': 'ru', 'format': 'post', 'instagram_link': 'none'}]
    assert task['production']['mode'] == 'account'
    assert task['production']['destination_url'] == 'https://uzstock.uz/news/10523'
    assert task['steps'] == ['news', 'copywriter', 'quality']
    assert not telegram_news.run_one(NOW + timedelta(minutes=1))
    assert len(rows('task')) == 1


@pytest.mark.parametrize('change', [{'paused': True}, {'automatic_news': False}, {'formats': ['image']}, {'rubrics': ['quarterly']}])
def test_channel_pause_opt_out_and_scope_prevent_default_news_work(monkeypatch, change):
    from marketing import telegram_news
    connected(monkeypatch, **change)
    assert not telegram_news.ensure_source(NOW)
    assert not telegram_news.run_one(NOW)
    assert rows('task') == []


def test_default_news_checks_connection_and_processing_pause(monkeypatch):
    from marketing import telegram_news
    connected(monkeypatch)
    monkeypatch.setenv('MARKETING_TELEGRAM_BOT_TOKEN', 'rotated')
    assert not telegram_news.ensure_source(NOW)
    assert rows('source') == []


def test_previously_connected_channel_adopts_defaults_once_without_reconnecting(monkeypatch):
    from marketing import telegram_news
    saved = connected(monkeypatch)
    with store.connection(write=True) as c:
        legacy = {key: value for key, value in saved.items() if key != 'automatic_news'}
        store.put(c, 'account', legacy, actor=OWNER, action='legacy_fixture', expected_version=saved['version'])
    assert telegram_news.upgrade(NOW)
    upgraded, = rows('account')
    assert upgraded['automatic_news'] and upgraded['valid_until'] is None
    assert channels.setup(upgraded)['ready']
    assert upgraded['mode'] == saved['mode']
    assert not telegram_news.upgrade(NOW + timedelta(minutes=1))
    permissions.save_account(OWNER, upgraded['id'],
        {key: value for key, value in {**upgraded, 'automatic_news': False, 'valid_until': saved['valid_until']}.items()
         if key in permissions.Account.model_fields}, upgraded['version'])
    assert not telegram_news.upgrade(NOW + timedelta(minutes=2))
    assert rows('account')[0]['automatic_news'] is False


@pytest.mark.parametrize('blocked_by', ['paused', 'expired', 'credential', 'processing'])
def test_legacy_upgrade_respects_stopped_or_unverified_channels(monkeypatch, blocked_by):
    from marketing import telegram_news
    saved = connected(monkeypatch)
    with store.connection(write=True) as c:
        legacy = {key: value for key, value in saved.items() if key != 'automatic_news'}
        if blocked_by == 'paused':
            legacy['paused'] = True
        if blocked_by == 'expired':
            legacy['valid_until'] = NOW.isoformat()
        store.put(c, 'account', legacy, actor=OWNER, action='legacy_fixture', expected_version=saved['version'])
        if blocked_by == 'processing':
            store.put(c, 'settings', {'id': 'pause', 'processing': True}, actor=OWNER, action='pause', expected_version=0)
    if blocked_by == 'credential':
        monkeypatch.setenv('MARKETING_TELEGRAM_BOT_TOKEN', 'rotated')
    assert not telegram_news.upgrade(NOW)
    assert 'automatic_news' not in rows('account')[0]


@pytest.mark.parametrize('legacy', [False, True])
def test_news_review_and_generation_publish_once_without_per_task_setup(monkeypatch, legacy):
    import json
    from marketing import news_review, worker
    from test_marketing_agents import output
    peer = TelegramPeer(monkeypatch)
    saved = account(automatic_news=True, valid_until=None)
    saved = channels.probe(OWNER, saved['id'], saved['version'], NOW)
    if legacy:
        with store.connection(write=True) as c:
            store.put(c, 'account', {key: value for key, value in saved.items() if key != 'automatic_news'},
                      actor=OWNER, action='legacy_fixture', expected_version=saved['version'])
    quote = 'S&P повысило рейтинг с BB- до BB. Прогноз стабильный.'
    monkeypatch.setattr(news_review, 'read_original', lambda url: 'Опубликована новость. ' + quote)
    class Team:
        def complete_json(self, system, user, **kwargs):
            context = json.loads(user)
            if 'article' in context:
                return {'supported': True, 'excerpt': quote, 'reason': 'Rating and issuer match'}
            if "UZStock's copywriter " in system:
                original = context['evidence'][0]
                return output('Draft ready', drafts=[{'account_id': saved['id'], 'language': 'ru',
                    'title': 'Кредитный рейтинг «Узбекнефтегаза»', 'body': 'По сообщению UzDaily, ' + quote,
                    'evidence_ids': [original['id']], 'claims': [], 'destination_url': original['destination_url'],
                    'founder_fact_ids': []}])
            if "UZStock's quality " in system:
                return output('Checked', reviews=[{'draft_id': d['id'], 'draft_digest': d['digest'], 'verdict': 'accept',
                    'reason': 'Matches the publisher excerpt', 'fragments': []} for d in context['drafts']])
            return output('Use the source attribution')
    for minute in range(5):
        worker.tick(model=Team(), fetch=lambda source: [material()], now=NOW + timedelta(minutes=minute))
    assert len(rows('task')) == 1 and rows('goal') == [] and rows('strategy') == []
    assert rows('candidate')[0]['status'] == 'published'
    assert len([call for call in peer.calls if call[0] == 'sendMessage']) == 1


def test_news_processing_pause_and_changed_evidence_stop_background_work(monkeypatch):
    from marketing import telegram_news, news_review
    connected(monkeypatch)
    with store.connection(write=True) as c:
        store.put(c, 'settings', {'id': 'pause', 'processing': True}, actor=OWNER, action='pause', expected_version=0)
    assert not telegram_news.ensure_source(NOW)
    with store.connection(write=True) as c:
        store.put(c, 'settings', {'id': 'pause', 'processing': False}, actor=OWNER, action='resume', expected_version=1)
    telegram_news.ensure_source(NOW)
    source, = rows('source')
    sources.import_materials(OWNER, source['id'], [material()], now=NOW)
    class Reviewer:
        def complete_json(self, *args, **kwargs):
            with store.connection(write=True) as c:
                old = store.list_items(c, 'evidence')[0]
                store.put(c, 'evidence', {**old, 'excerpt': 'Correction'}, actor=OWNER, action='corrected', expected_version=old['version'])
            return {'supported': True, 'excerpt': 'S&P повысило рейтинг с BB- до BB.', 'reason': 'Old text only'}
    news_review.run_one(Reviewer(), NOW, fetch_text=lambda url: 'Новость: S&P повысило рейтинг с BB- до BB. Прогноз стабильный.')
    assert rows('evidence')[0]['status'] == 'candidate'
    assert not telegram_news.run_one(NOW)


def test_transient_model_failure_retries_without_an_owner_task_form(monkeypatch):
    from marketing import agents, telegram_news
    connected(monkeypatch)
    telegram_news.ensure_source(NOW)
    source, = rows('source')
    sources.import_materials(OWNER, source['id'], [material()], now=NOW)
    original, = rows('evidence')
    sources.verify_evidence(OWNER, original['id'], original['version'], 'Checked publisher')
    telegram_news.run_one(NOW)
    class Offline:
        def complete_json(self, *args, **kwargs):
            raise RuntimeError('temporary outage')
    assert agents.run_one(Offline(), NOW)
    assert rows('task')[0]['status'] == 'error'
    assert not telegram_news.run_one(NOW + timedelta(seconds=30))
    assert telegram_news.run_one(NOW + timedelta(minutes=2))
    assert rows('task')[0]['status'] == 'queued'
    assert len(rows('task')) == 1


def test_connection_form_only_needs_channel_and_reuses_saved_mode(monkeypatch):
    from marketing import telegram_news
    peer = TelegramPeer(monkeypatch)
    saved = telegram_news.connect(OWNER, '-100123', expected_version=0, now=NOW)
    assert saved['connection_status'] == 'connected' and saved['automatic_news']
    assert saved['mode'] == 'automatic' and saved['valid_until'] is None
    assert saved['rubrics'] == ['news'] and saved['formats'] == ['post']
    assert permissions.can_release(saved, {'publication_type': 'organic', 'rubric': 'news',
                                          'format': 'post', 'language': 'ru'}, NOW + timedelta(days=365))[0]
    assert all(method.startswith('get') for method, _, _ in peer.calls)
    assert rows('task') == [] and rows('delivery') == []
    changed = permissions.save_account(OWNER, saved['id'],
        {key: value for key, value in {**saved, 'mode': 'manual'}.items() if key in permissions.Account.model_fields}, saved['version'])
    updated = telegram_news.connect(OWNER, '-100123', expected_version=changed['version'], now=NOW)
    assert updated['mode'] == 'manual'
    assert not permissions.can_release({**updated, 'rubrics': ['quarterly']},
        {'publication_type': 'organic', 'rubric': 'quarterly', 'format': 'post', 'language': 'ru'}, NOW)[0]


def test_daily_limit_is_persistent_and_manual_tasks_also_prevent_duplicates(monkeypatch):
    from marketing import telegram_news, agents
    connected(monkeypatch)
    telegram_news.ensure_source(NOW)
    source, = rows('source')
    sources.import_materials(OWNER, source['id'], [material(str(i), url=f'https://example.test/news/{i}') for i in range(4)], now=NOW)
    for original in rows('evidence'):
        sources.verify_evidence(OWNER, original['id'], original['version'], 'Checked publisher')
    original = rows('evidence')[0]
    agents.start(OWNER, kind='content', message='Already requested manually', evidence_ids=[original['id']],
        production={'event_id': 'owner-custom-event-key', 'rubric': 'news', 'mode': 'draft',
                    'expires_at': (NOW + timedelta(hours=4)).isoformat(),
                    'targets': [{'account_id': 'tg', 'languages': ['ru'], 'primary_language': 'ru', 'format': 'post'}]})
    for _ in range(2):
        assert telegram_news.run_one(NOW)
        with store.connection(write=True) as c:
            task = next(t for t in store.list_items(c, 'task') if t['status'] == 'queued' and t.get('editorial'))
            assert original['id'] not in task['evidence_versions']
            store.put(c, 'task', {**task, 'status': 'complete'}, actor=OWNER, action='test_completed', expected_version=task['version'])
    assert not telegram_news.run_one(NOW + timedelta(minutes=2))
    assert len(rows('task')) == 3


@pytest.mark.parametrize('quote,supported,verified', [
    ('S&P повысило рейтинг с BB- до BB.', True, True),
    ('S&P повысило рейтинг до AAA.', True, False),
    ('S&P повысило рейтинг с BB- до BB.', False, False),
])
def test_news_review_requires_support_and_an_exact_publisher_excerpt(monkeypatch, quote, supported, verified):
    from marketing import telegram_news, news_review
    connected(monkeypatch)
    telegram_news.ensure_source(NOW)
    source, = rows('source')
    sources.import_materials(OWNER, source['id'], [material()], now=NOW)
    class Reviewer:
        def complete_json(self, *args, **kwargs):
            return {'supported': supported, 'excerpt': quote, 'reason': 'Compared the rating and issuer'}
    assert news_review.run_one(Reviewer(), NOW, fetch_text=lambda url: 'Новость: S&P повысило рейтинг с BB- до BB. Прогноз стабильный.')
    original, = rows('evidence')
    assert (original['status'] == 'verified') is verified
    assert not news_review.run_one(Reviewer(), NOW, fetch_text=lambda url: pytest.fail('Do not repeat the same review'))
    if verified:
        assert original['verification_reason'].startswith('Publisher text checked')
        assert original['data']['reported_excerpt'] == quote
    assert telegram_news.run_one(NOW) is verified
