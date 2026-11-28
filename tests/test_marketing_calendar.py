"""Weekly editions bind each future event to its current original and date."""
from datetime import timedelta
import json

import pytest

from marketing import agents, automation, content, sources, store
from test_marketing_core import NOW, candidate, isolated  # noqa: F401
from test_marketing_execution import model_clock  # noqa: F401
from test_marketing_automation import rows, setup_rule, update_rule, verified
from test_marketing_production import ProductionModel


def rule(**changes):
    return setup_rule(**{
        'rubric': 'calendar', 'calendar_time': '13:00', 'calendar_day': 0,
        'mode': 'account', 'max_daily': 10, **changes})


def announcement(key='meeting', *, at=None, **changes):
    kind = changes.get('data', {}).get('event_type', 'meeting')
    excerpts = {'meeting': 'Объявлено собрание акционеров. Проверьте повестку в первоисточнике.',
                'report': 'Объявлена дата отчёта. Следите за раскрытием в первоисточнике.'}
    return verified(key, **{
        'canonical_event_id': key, 'suggested_rubric': 'calendar', 'entity': 'HMKB',
        'url': f'https://openinfo.uz/facts/{key}', 'title': f"{changes.get('entity', 'HMKB')} · {key}",
        'destination_url': f'https://uzstock.uz/news/{key}',
        'published_at': (NOW - timedelta(days=20)).isoformat(),
        'event_at': (at or NOW + timedelta(days=2)).isoformat(),
        'data': {'event_type': 'meeting'}, 'units': {},
        'excerpt': excerpts.get(kind, 'Проверьте объявленные условия в первоисточнике.'), **changes})


class CalendarModel(ProductionModel):
    def __init__(self, *, omit_last=False):
        super().__init__()
        self.omit_last = omit_last

    def complete_json(self, system, user, **options):
        result = super().complete_json(system, user, **options)
        context = json.loads(user)
        for draft in result.get('drafts', []):
            originals = context['evidence'][:-1] if self.omit_last else context['evidence']
            from marketing.trends import event_groups
            draft.update(title='Календарь объявленных событий', body='Подготовка календаря',
                evidence_ids=[row['id'] for row in originals], claims=[],
                destination_url=context['production']['destination_url'],
                digest_items=[{'evidence_ids': [row['id'] for row in group], 'text': group[0]['excerpt']}
                              for group in event_groups(originals)])
        return result


def finish(model=None):
    model = model or CalendarModel()
    for _ in range(8):
        assert agents.run_one(model, NOW)
    return rows('candidate')[0], model


def test_weekly_calendar_waits_for_cutoff_keeps_old_announcements_and_renders_ordered_current_dates():
    owner_rule = rule()
    later = announcement('meeting', at=NOW + timedelta(days=3))
    earlier = announcement('report', at=NOW + timedelta(days=1), entity='UZTL', data={'event_type': 'report'})
    reprint = announcement('meeting-reprint', canonical_event_id='meeting', at=NOW + timedelta(days=3))
    announcement('outside-week', at=NOW + timedelta(days=7))
    assert not automation.run_one(NOW - timedelta(minutes=1))
    assert automation.run_one(NOW)
    task, = rows('task')
    assert task['production']['period'] == '2026-11-23'
    assert set(task['evidence_versions']) == {later['id'], earlier['id'], reprint['id']}
    assert task['editorial']['calendar_cutoff'] == '2026-11-23T13:00:00+05:00'
    item, model = finish()
    assert item['status'] == 'ready', item['check']
    assert len(item['digest_items']) == 2
    assert item['body'].index('24.11.2026') < item['body'].index('26.11.2026')
    assert 'Отчёт' in item['body'] and 'Собрание' in item['body']
    for original in (earlier, later):
        assert original['entity'] in item['body']
        assert original['url'] in item['body'] and original['destination_url'] in item['body']
    assert model.calls[-1][1]['drafts'][0]['body'] == item['body']
    assert not automation.run_one(NOW + timedelta(hours=1))
    update_rule(owner_rule, title='Новая подача той же недели')
    assert not automation.run_one(NOW + timedelta(hours=1))
    assert len(rows('task')) == 1 and rows('delivery') == []


@pytest.mark.parametrize('changes', [
    {'event_at': (NOW - timedelta(minutes=1)).isoformat()},
    {'event_at': (NOW + timedelta(days=7)).isoformat()},
    {'data': {'event_type': 'rumour'}},
    {'destination_url': 'https://uzstock.uz/'},
])
def test_calendar_does_not_fill_an_empty_week_with_past_outside_or_unannounced_events(changes):
    rule()
    announcement(**changes)
    assert not automation.run_one(NOW)
    assert rows('task') == [] and rows('candidate') == []


def test_conflicting_announced_dates_cannot_be_selected_as_two_calendar_events():
    rule()
    announcement('meeting')
    announcement('reprint', canonical_event_id='meeting', at=NOW + timedelta(days=3))
    assert not automation.run_one(NOW)
    assert rows('task') == []


def test_a_rescheduled_notice_before_assignment_uses_the_amended_date_once():
    rule()
    first = announcement()
    current = announcement(at=NOW + timedelta(days=3))
    assert first['id'] == current['id'] and current['version'] > first['version']
    assert automation.run_one(NOW)
    item, _ = finish()
    assert item['status'] == 'ready', item['check']
    assert '26.11.2026' in item['body'] and '25.11.2026' not in item['body']
    announcement(at=NOW + timedelta(days=4))
    checked = content.check_candidate(item['id'], NOW)
    assert checked['status'] == 'skipped'
    assert not automation.run_one(NOW + timedelta(minutes=1))
    assert len(rows('candidate')) == 1 and rows('delivery') == []


def test_a_weekly_calendar_cannot_silently_omit_an_assigned_event():
    rule()
    announcement('meeting')
    announcement('report', at=NOW + timedelta(days=1), data={'event_type': 'report'})
    assert automation.run_one(NOW)
    item, _ = finish(CalendarModel(omit_last=True))
    assert item['status'] == 'skipped' and 'selected event' in item['check']['reason']
    assert rows('delivery') == []


def test_calendar_paragraph_cannot_borrow_another_events_date():
    rule()
    first = announcement('meeting')
    second = announcement('report', at=NOW + timedelta(days=3), data={'event_type': 'report'})
    item = candidate('manual-week', rubric='calendar', entity='', period='2026-11-23', claims=[],
        body='Will be assembled', title='Календарь недели', evidence_ids=[first['id'], second['id']],
        digest_items=[{'evidence_ids': [first['id']], 'text': 'Собрание состоится 26.11.2026.'},
                      {'evidence_ids': [second['id']], 'text': second['excerpt']}])
    result = content.check_candidate(item['id'], NOW)
    assert result['status'] == 'skipped' and 'date' in result['check']['reason']


@pytest.mark.parametrize('changes', [
    {'calendar_day': 7}, {'calendar_time': '25:00'}, {'rubric': 'news'},
    {'target': {'account_id': 'tg', 'languages': ['ru'], 'primary_language': 'ru', 'format': 'image'}},
])
def test_calendar_day_cutoff_and_text_format_are_scoped_to_a_weekly_rule(changes):
    with pytest.raises(ValueError):
        rule(**changes)


def test_sunday_edition_covers_the_next_tashkent_week_and_can_catch_up_on_monday():
    sunday = NOW - timedelta(days=1)
    owner_rule = rule(calendar_day=6, calendar_time='13:00', enabled=False, starts_on='2026-11-22')
    from marketing import calendar_events
    cut, start, end = calendar_events.window(owner_rule, NOW)
    assert cut.date() == sunday.date()
    assert start.isoformat() == '2026-11-23' and end.isoformat() == '2026-11-30'
    assert calendar_events.window(owner_rule, sunday - timedelta(minutes=1)) is None
