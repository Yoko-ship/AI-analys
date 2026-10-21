"""21 Oct: BECMP's eight extra rows must not freeze IPTB and the market."""
import asyncio
from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest
from collectors.openinfo import market_fallback as archive
from collectors.financials import trading, market, delivery

IPTB = 'UZ7054570005'
KASU = 'UZ7028660007'
BECMP = 'UZ702845K017'


@pytest.fixture
def real_source(monkeypatch):
    evidence = json.loads(gzip.decompress(Path('tests/fixtures/openinfo/market_20261021.json.gz').read_bytes()))
    parts = evidence['securities']
    rows = [r for p in parts.values() for r in p['results']]
    state = {'parts': parts, 'rows': rows, 'calls': [], 'broken': None}

    def get(client, path, params):
        state['calls'].append((path, params.copy()))
        if path.endswith('conclusions/'):
            return {'ticker': params['isu_cd'], 'results': [{'date': '2026-10-20',
                'open': 1, 'close': 1, 'high': 1, 'low': 1, 'change': 0,
                'trading_volume': 1, 'trading_value': 1}]}
        if 'start_date' not in params:
            return {'results': [rows[0]]}
        isin = params.get('isu_cd')
        if isin:
            if isin == state['broken']:
                raise ConnectionError('one security unavailable')
            p = deepcopy(parts[isin])
            # Wrong-security and moving-response controls can modify this.
            return state.get('mutate', lambda p, i: p)(p, isin)
        return {'count': sum(p['count'] for p in parts.values()),
                'total_pages': 1, 'page_size': 20000, 'current_page': 1,
                'has_next': False, 'results': deepcopy(rows)}

    monkeypatch.setattr(archive, '_json_get', get)
    monkeypatch.setattr(archive, '_session_finished', lambda day: True)
    return state


def test_real_becmp_surplus_does_not_freeze_verified_iptb_and_kasu(real_source):
    data = archive.fetch_latest_trade_stats(session=object())
    assert data.get('partial') and not data['complete']
    assert set(data['stats']) == {IPTB, KASU}
    assert data['validation']['withheld'] == [{'isin': BECMP, 'ticker': 'BECMP'}]
    assert data['stats'][IPTB]['trade_count'] == 498
    assert data['stats'][KASU]['trade_count'] == 507  # genuine identical trades survive
    assert all(q['isin'] != BECMP for q in data['quotes'])
    assert all(b['isin'] != BECMP for b in data['intraday'])
    assert data['trade_date'] == '20261021'


@pytest.mark.parametrize('problem', ['timeout', 'wrong_security', 'short', 'changed'])
def test_one_unverifiable_security_does_not_block_other_verified_rows(real_source, problem):
    if problem == 'timeout':
        real_source['broken'] = IPTB
    else:
        def mutate(p, isin):
            if isin == IPTB:
                if problem == 'wrong_security':
                    p['results'][0]['isin_code'] = KASU
                elif problem == 'short':
                    p['results'].pop()
                else:
                    p['results'][0]['trade_price'] += 1
            return p
        real_source['mutate'] = mutate
    data = archive.fetch_latest_trade_stats(session=object())
    assert data.get('partial') and set(data['stats']) == {KASU}
    assert {r['isin'] for r in data['validation']['withheld']} == {IPTB, BECMP}


def test_no_verified_security_means_no_publishable_data(real_source):
    real_source['mutate'] = lambda p, isin: {**p, 'count': p['count'] + 1}
    data = archive.fetch_latest_trade_stats(session=object())
    assert not data.get('partial') and not data['complete'] and not data['stats']


def test_partial_collection_publishes_verified_rows_without_marking_session_complete(real_source, monkeypatch):
    data = archive.fetch_latest_trade_stats(session=object())
    assert data.get('partial')
    monkeypatch.setattr(trading, 'SESSION_DATE', '2026-10-21')
    monkeypatch.setattr(archive, 'fetch_latest_trade_stats', lambda **kw: deepcopy(data))
    monkeypatch.setattr(market, 'board_securities', lambda: [
        {'isin': BECMP, 'last_trade_date': '2026-10-20', '_market': 'STK'}])
    monkeypatch.setattr(market, 'SKIP_QUOTES', False)
    monkeypatch.setattr(market, 'audit_board', lambda: 0)
    monkeypatch.setattr(archive, 'fetch_quotes', lambda targets, **kw: [] if not targets else pytest.fail('withheld security must not be fetched/pushed'))
    pushed, stamps = [], []
    monkeypatch.setattr(delivery, '_post', lambda path, body: pushed.append((path, deepcopy(body))) or 0)
    monkeypatch.setattr(delivery, '_stamp_step', lambda *args: stamps.append(args))
    assert trading.push_trade_stats() == 0
    stats = next(body for path, body in pushed if path.endswith('trade-stats'))
    assert {r['isin'] for r in stats['rows']} == {IPTB, KASU}
    assert not any(s[0] in {'trade_stats', 'official_quotes'} for s in stamps)
    facts = [r for path, b in pushed if path.endswith('facts') for r in b['rows']]
    status = json.loads(next(r['value'] for r in facts if r['field'] == 'market_validation'))
    assert status['partial'] and status['trade_date'] == '20261021'
    assert status['withheld'][0]['ticker'] == 'BECMP'


def test_market_endpoints_expose_partial_totals_and_delayed_security(monkeypatch):
    import catalogue.facts as facts
    from server.market import routes
    status = {'partial': True, 'trade_date': '20261021', 'withheld': [{'isin': BECMP, 'ticker': 'BECMP'}]}
    monkeypatch.setattr(facts, 'get_facts', lambda *a: [{'field': 'market_validation', 'value_text': json.dumps(status)}])
    monkeypatch.setattr(routes.catalogue_market_store, 'get_all_trade_stats', lambda: {
        IPTB: {'trade_date': '20261021', 'total_value': 10, 'total_qty': 2, 'trade_count': 1}})
    for endpoint in (routes.api_market_trade_stats, routes.api_market_trades):
        body = asyncio.run(endpoint())
        assert body['validation'] == status


def test_partial_session_is_retried_even_if_quote_stamp_is_current(monkeypatch):
    monkeypatch.setattr(trading, '_published_session', lambda: (None, '20261020'))
    monkeypatch.setattr(archive, 'latest_session', lambda: '20261021')
    monkeypatch.setattr(archive, 'conclusions_posted', lambda d: False)
    monkeypatch.setattr(archive, '_session_finished', lambda d: True)
    assert trading._session_to_publish() == 'go'
