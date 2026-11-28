"""Saved channel schedules control automatic news preparation and dispatch."""
from datetime import timedelta

import pytest
from pydantic import ValidationError

from marketing import permissions, sources, store, telegram_news
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401
from test_marketing_telegram_news import connected, material, rows


def inventory(monkeypatch, **schedule):
    saved = connected(monkeypatch, **schedule)
    telegram_news.ensure_source(NOW)
    sources.import_materials(OWNER, rows('source')[0]['id'],
        [material(str(i), url=f'https://example.test/news/{i}') for i in range(4)], now=NOW)
    for item in rows('evidence'):
        sources.verify_evidence(OWNER, item['id'], item['version'], 'Checked publisher')
    return saved


@pytest.mark.parametrize('changes', [
    {'news_daily_limit': 0}, {'news_daily_limit': 25}, {'news_daily_limit': 1.5},
    {'news_publish_times': ['10:00']}, {'news_publish_times': ['10:00', '10:00']},
    {'news_publish_times': ['08:59', '10:00']}, {'news_publish_times': ['10:00', '21:00']},
    {'news_publish_times': ['10:00', '10:15']},
    {'news_publish_times': ['10:00:01', '14:00']}, {'news_publish_times': ['10:00Z', '14:00']},
])
def test_invalid_channel_schedule_is_rejected(monkeypatch, changes):
    with pytest.raises(ValidationError):
        connected(monkeypatch, **changes)


def test_times_are_sorted_and_schedule_survives_reconnect(monkeypatch):
    saved = connected(monkeypatch, news_daily_limit=3, news_publish_times=['18:00', '10:00', '14:00'])
    assert saved['news_publish_times'] == ['10:00:00', '14:00:00', '18:00:00']
    updated = telegram_news.connect(OWNER, '-100123', saved['version'], NOW)
    assert updated['news_daily_limit'] == 3 and updated['news_publish_times'] == saved['news_publish_times']


def test_slots_prepare_ahead_once_and_skip_missed_times(monkeypatch):
    inventory(monkeypatch, news_daily_limit=3, news_publish_times=['10:00', '14:00', '18:00'])
    assert not telegram_news.run_one(NOW - timedelta(minutes=1))  # 12:59, too early for 14:00
    assert telegram_news.run_one(NOW)
    first, = rows('task')
    assert permissions.timestamp(first['production']['not_before']) == NOW + timedelta(hours=1)
    assert permissions.timestamp(first['production']['expires_at']) == NOW + timedelta(hours=1, minutes=15)
    assert not telegram_news.run_one(NOW + timedelta(minutes=5))
    # A missed, still-queued slot must not hold up the next one after downtime.
    assert telegram_news.run_one(NOW + timedelta(hours=4))
    assert len(rows('task')) == 2
    assert not telegram_news.run_one(NOW + timedelta(hours=5, minutes=16))
    with store.connection() as c, pytest.raises(MarketingError, match='current'):
        telegram_news.guard(c, first, NOW + timedelta(hours=1, minutes=15))


def test_schedule_edits_release_unsent_slots_without_resetting_sent_quota(monkeypatch):
    saved = inventory(monkeypatch, news_daily_limit=1, news_publish_times=['14:00'])
    assert telegram_news.run_one(NOW)
    old, = rows('task')
    data = {k: saved[k] for k in permissions.Account.model_fields}
    saved = permissions.save_account(OWNER, saved['id'], {**data, 'news_publish_times': ['13:30']}, saved['version'])
    assert telegram_news.run_one(NOW)
    with store.connection(write=True) as c:
        with pytest.raises(MarketingError, match='settings'):
            telegram_news.guard(c, old, NOW)
        current = next(t for t in rows('task') if t['id'] != old['id'])
        store.put(c, 'candidate', {'id': 'sent', 'origin_task': current['id'], 'status': 'published'},
                  actor=OWNER, action='test_sent', expected_version=0)
    permissions.save_account(OWNER, saved['id'], {**data, 'news_publish_times': ['14:00']}, saved['version'])
    assert not telegram_news.run_one(NOW)


def test_ready_mode_obeys_window_and_does_not_carry_quota_across_tashkent_days(monkeypatch):
    saved = inventory(monkeypatch, news_daily_limit=1, window_start='00:00', window_end='23:59')
    late = NOW.replace(hour=18, minute=50)  # 23:50 Tashkent
    assert telegram_news.run_one(late)
    task, = rows('task')
    assert permissions.timestamp(task['production']['expires_at']) == late.replace(minute=59)
    assert not telegram_news.run_one(late.replace(minute=59))
    tomorrow = late + timedelta(minutes=10)
    with store.connection() as c:
        assert telegram_news.pending(c, saved, tomorrow)
        with pytest.raises(MarketingError, match='current'):
            telegram_news.guard(c, task, tomorrow)


def test_evidence_must_still_be_fresh_at_the_planned_time(monkeypatch):
    inventory(monkeypatch, news_daily_limit=1, news_publish_times=['14:00'])
    with store.connection(write=True) as c:
        for item in store.list_items(c, 'evidence'):
            store.put(c, 'evidence', {**item, 'expires_at': (NOW + timedelta(minutes=20)).isoformat()},
                      actor=OWNER, action='test_expiry', expected_version=item['version'])
    assert not telegram_news.run_one(NOW)
