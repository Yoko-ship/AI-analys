"""Actual notices whose portal metadata contradicts the meeting text."""
import json
from pathlib import Path
import pytest
import corporate_events as ce

CASES = json.loads((Path(__file__).parent / 'fixtures/openinfo/announcement_dates.json').read_text())

@pytest.mark.parametrize('detail,publication,expected,time', [
    (CASES[0], '2026-10-02T17:33:06', '2026-10-23', '11:00'),
    (CASES[1], '2026-10-07T10:09:51', '2026-10-31', '10:00'),
])
def test_body_meeting_date_overrides_portal_metadata(detail, publication, expected, time):
    event = ce.from_announcement({'announcement_id': detail['announcement_id'],
        'pub_date': publication, 'meeting_date': publication}, detail)
    assert event['event_date'] == expected
    assert event['meeting_time'] == time
    assert event['published_at'] == publication
    assert event['date_source'] == 'announcement_body'
    assert event['date_conflict'] is True
    assert any(expected in text for text in event['summary'].values())
    assert event['date_evidence']


def test_registry_and_registration_dates_never_become_meeting_dates():
    from announcement_dates import meeting_schedule
    detail = {'content': [{'text': 'Реестр для участия в собрании, которое состоится 27 октября 2026 года.'},
                          {'text': 'Регистрация на собрание 31 октября 2026 года в 09:00.'}]}
    assert meeting_schedule(detail)['date'] is None


def test_conflicting_body_dates_require_review():
    from announcement_dates import meeting_schedule
    detail = {'content': [{'text': 'Собрание состоится 31 октября 2026 года в 10:00.'},
                          {'text': 'Собрание состоится 1 ноября 2026 года в 10:00.'}]}
    assert meeting_schedule(detail)['ambiguous'] is True
    assert meeting_schedule(detail)['date'] is None

@pytest.mark.parametrize('text,expected', [
    ('Общее собрание состоится 25.11.2026 в 11:00.', '2026-11-25'),
    ('The shareholders meeting will be held on 2026-11-25 at 11:00.', '2026-11-25'),
    ('2026-yil 25-noyabr kuni soat 11:00da umumiy yig‘ilishi bo‘lib o‘tadi.', '2026-11-25'),
])
def test_other_supported_date_forms(text, expected):
    from announcement_dates import meeting_schedule
    assert meeting_schedule({'content': [{'text': text}]})['date'] == expected


def test_calendar_moves_corrected_meeting_across_months_but_keeps_notice_publication(monkeypatch):
    import calendar_events as calendar
    import meetings
    raw = {'announcement_id': '21414', 'organization': 'BMKB-Agromash',
           'pub_date': '2026-10-07T10:09:51', 'meeting_date': '2026-10-07T10:07:00'}
    document = ce.from_announcement(raw, CASES[1])
    monkeypatch.setattr(meetings, 'ensure_snapshot', lambda: {})
    monkeypatch.setattr(meetings, 'read_window', lambda lo, hi: [raw] if lo <= raw['meeting_date'] < hi else [])
    monkeypatch.setattr(meetings, 'read_published', lambda lo, hi: [raw])
    monkeypatch.setattr(ce, 'read_announcement_documents', lambda: [document], raising=False)
    assert calendar._meetings('2026-10-07', '2026-10-08') == []
    event, = calendar._meetings('2026-10-31', '2026-11-01')
    assert event['date'] == '2026-10-31' and event['time'] == '10:00'
    assert event['details']['pub_date'] == raw['pub_date']
    notice, = calendar._notices('2026-10-07', '2026-10-08')
    assert notice['date'] == '2026-10-07'
    assert notice['details']['meeting_date'] == '2026-10-31'


def test_a_conflicting_meeting_body_removes_the_unreliable_calendar_date(monkeypatch):
    import calendar_events as calendar
    import meetings
    raw = {'announcement_id':'conflict','meeting_date':'2026-10-07','pub_date':'2026-10-02'}
    detail = {'content':[{'text':'Собрание состоится 7 октября 2026 года.'}, {'text':'Собрание состоится 8 октября 2026 года.'}]}
    document = ce.from_announcement(raw, detail)
    monkeypatch.setattr(meetings, 'ensure_snapshot', lambda: {})
    monkeypatch.setattr(meetings, 'read_window', lambda lo, hi: [raw])
    monkeypatch.setattr(ce, 'read_announcement_documents', lambda: [document], raising=False)
    assert document['confidence'] == 'review'
    assert calendar._meetings('2026-10-01', '2026-11-01') == []


@pytest.mark.parametrize('detail', json.loads((Path(__file__).parent / 'fixtures/openinfo/announcement_nonmeeting_dates.json').read_text()))
def test_board_decisions_and_previously_published_meetings_are_not_the_new_meeting(detail):
    from announcement_dates import meeting_schedule
    assert meeting_schedule(detail)['date'] is None


def test_contradictory_historical_body_date_is_reviewed_not_promoted_as_confirmed():
    event = ce.from_announcement({'announcement_id':'21352','meeting_date':'2026-06-30','pub_date':'2026-09-08'}, CASES[2])
    assert event['event_date'] is None
    assert event['date_unresolved'] is True
    assert event['confidence'] == 'review'
    assert '2025' in event['date_evidence']


@pytest.mark.parametrize('time', ['11-00', '11.00', '11 00'])
def test_source_time_separators_are_not_lost(time):
    from announcement_dates import meeting_schedule
    schedule = meeting_schedule({'content':[{'text':f'Умумий йиғилиши 2026 йил 9 ноябрь куни соат {time} да ўтказилади.'}]})
    assert schedule['time'] == '11:00'
