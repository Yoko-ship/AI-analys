"""Last-viewed changes use like-for-like periods, sources and market sessions."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

SELECTION = dict(tickers=['HMKB', 'IPKY'], period='latest', standard='NSBU', scope='separate', unit='billion')


def figures(period='2025', profit=1704969118000, price=100, day='2026-10-21'):
    source = {'document_id': 31438, 'url': 'https://openinfo.uz/ru/reports/to_pdf31438/', 'period': period}
    return {'ok': True, 'period': period, 'standard': 'NSBU', 'scope': 'separate', 'currency': 'UZS',
            'generated_at': '2026-10-21T12:00:00Z', 'companies': [
                {'ticker': ticker, 'status': 'available', 'period': period, 'source': source, 'market_as_of': day, 'metrics': {
                    'net_profit': {'value': profit, 'unit': 'UZS', 'period': period, 'source': source},
                    'roe': {'value': 26.51, 'unit': '%', 'period': period, 'source': source},
                    'price': {'value': price, 'unit': 'UZS', 'as_of': day, 'source': {'url': 'https://uzse.uz'}},
                    'pe': {'value': 7.2, 'unit': 'x', 'base_period': '2025', 'period': period, 'source': source},
                }} for ticker in SELECTION['tickers']]}


def test_first_visit_and_identical_figures_do_not_invent_changes():
    from server.comparison.updates import snapshot, difference
    before = snapshot(figures(), SELECTION)
    assert difference(None, before) == []
    after = figures();after['generated_at'] = '2026-10-23T12:00:00Z'
    after['companies'][0]['name'] = 'Updated legal display name'
    assert snapshot(after, SELECTION) == before
    assert difference(before, before) == []


def test_same_period_revision_and_price_change_retain_dates_and_sources():
    from server.comparison.updates import snapshot, difference
    before = snapshot(figures(), SELECTION)
    current = figures(profit=1704969119000, price=110, day='2026-10-22')
    changes = difference(before, snapshot(current, SELECTION))
    profit = next(c for c in changes if c['ticker'] == 'HMKB' and c.get('metric') == 'net_profit')
    assert profit['kind'] == 'revised_figure' and profit['delta'] == 1000
    assert profit['source']['url'].startswith('https://openinfo.uz/')
    price = next(c for c in changes if c['ticker'] == 'HMKB' and c.get('metric') == 'price')
    assert price['kind'] == 'market_change' and price['percent_change'] == 10
    assert price['before_date'] == '2026-10-21' and price['after_date'] == '2026-10-22'


def test_new_nine_month_report_never_creates_growth_against_full_year_profit():
    from server.comparison.updates import snapshot, difference
    before = snapshot(figures(), SELECTION)
    current = snapshot(figures('2026Q3', 1480422343000, 110, '2026-10-22'), SELECTION)
    changes = difference(before, current)
    assert len([c for c in changes if c['kind'] == 'new_period']) == 2
    assert not any(c.get('metric') in {'net_profit', 'roe', 'pe'} for c in changes)
    assert any(c.get('metric') == 'price' for c in changes)


def test_scope_changes_missing_values_and_older_quotes_never_become_numeric_moves():
    from server.comparison.updates import snapshot, difference
    before = snapshot(figures(), SELECTION)
    data = figures(price=110, day='2026-10-20')
    data['companies'][0]['metrics']['net_profit']['value'] = None
    changes = difference(before, snapshot(data, SELECTION))
    assert not any(c.get('metric') == 'price' for c in changes)
    missing = next(c for c in changes if c['ticker'] == 'HMKB' and c.get('metric') == 'net_profit')
    assert missing['kind'] == 'data_unavailable' and 'delta' not in missing
    assert difference(before, snapshot(data, {**SELECTION, 'scope': 'consolidated'})) == []


def test_replacement_filing_and_valuation_basis_are_explicit_changes():
    from server.comparison.updates import snapshot, difference
    before = snapshot(figures(), SELECTION)
    data = figures()
    data['companies'][0]['source'] = {'document_id': 99999, 'url': 'https://openinfo.uz/revised.pdf'}
    data['companies'][0]['metrics']['pe'].update(value=8.1, base_period='TTM 2026Q3')
    changes = difference(before, snapshot(data, SELECTION))
    assert any(c['kind'] == 'filing_updated' and c['ticker'] == 'HMKB' for c in changes)
    basis = next(c for c in changes if c.get('metric') == 'pe')
    assert basis['kind'] == 'basis_changed' and 'percent_change' not in basis


@pytest.mark.parametrize('quote', [0, -1])
def test_nonpositive_quotes_cannot_be_reported_as_a_complete_price_collapse(quote):
    from server.comparison.updates import snapshot, difference
    before = snapshot(figures(), SELECTION)
    after = snapshot(figures(price=quote, day='2026-10-22'), SELECTION)
    changes = difference(before, after)
    prices = [c for c in changes if c.get('metric') == 'price']
    assert prices and all(c['kind'] == 'data_unavailable' for c in prices)
    assert all('percent_change' not in c for c in prices)


def test_saving_normalizes_selection_before_capturing_a_server_baseline(monkeypatch):
    from server.comparison import service, updates
    calls = []
    monkeypatch.setattr(service, 'compare', lambda *a, **kw: figures())
    repository = SimpleNamespace(save=lambda *a: calls.append(a) or {})
    updates.save(repository, 1, {'name': ' Banks ', **SELECTION, 'tickers': ['hmkb', 'ipky']})
    assert calls[0][1]['tickers'] == ['HMKB', 'IPKY']
    assert calls[0][2]['context']['tickers'] == ['HMKB', 'IPKY']


@pytest.fixture
def api_source(monkeypatch):
    import api, web_auth
    from identity.comparisons import snapshot_key
    from server.comparison import service, updates
    baseline = updates.snapshot(figures(), SELECTION)
    record = {'id': 7, 'name': 'Banks', 'selection': SELECTION, 'seen_snapshot': baseline,
              'seen_at': datetime(2026, 10, 21, tzinfo=timezone.utc)}
    writes = []
    repository = SimpleNamespace(get=lambda uid, identifier: deepcopy(record) if uid == 1 and identifier == 7 else None,
                                 mark_seen=lambda *args: writes.append(args) or {'last_seen_at': '2026-10-23T12:00:00Z'})
    monkeypatch.setattr(web_auth.web_auth_store, 'comparisons', repository)
    monkeypatch.setattr(web_auth.web_auth_store.sessions, 'get_user_by_token', lambda t: SimpleNamespace(id=1 if t == 'alice' else 2))
    monkeypatch.setattr(service, 'compare', lambda *args, **kw: figures(price=110, day='2026-10-22'))
    return TestClient(api.app), writes, record, snapshot_key


def test_inspection_does_not_clear_badges_and_only_exact_displayed_data_can_be_seen(api_source):
    client, writes, record, key = api_source
    path = '/api/saved-comparisons/7/updates';headers = {'Authorization': 'Bearer alice'}
    result = client.get(path, headers=headers)
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    body = result.json()
    assert body['updated'] is True and body['baseline_key'] == key(record['seen_snapshot'])
    assert writes == []
    wrong = client.post('/api/saved-comparisons/7/seen', headers=headers,
                        json={'snapshot_key': '0' * 64, 'baseline_key': body['baseline_key']})
    assert wrong.status_code == 409 and writes == []
    marked = client.post('/api/v2/saved-comparisons/7/seen', headers=headers,
                         json={'snapshot_key': body['snapshot_key'], 'baseline_key': body['baseline_key']})
    assert marked.status_code == 200 and writes[0][0:2] == (1, 7)


def test_updates_and_seen_are_private_and_missing_comparisons_cannot_be_inspected(api_source):
    client, writes, _, _ = api_source
    for suffix, method in [('updates', client.get), ('seen', client.post)]:
        payload = {'json': {'snapshot_key': '0' * 64, 'baseline_key': 'none'}} if suffix == 'seen' else {}
        assert method('/api/saved-comparisons/7/' + suffix, **payload).status_code == 401
        assert method('/api/saved-comparisons/7/' + suffix, headers={'Authorization': 'Bearer bob'}, **payload).status_code == 404
    assert writes == []
