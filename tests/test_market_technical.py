"""Admin screener metrics from daily exchange history, never invented prices."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api
import catalogue.market_store as quotes
import securities_catalog as securities
import server.auth.access as access


def history(closes, start=date(2025, 1, 1), **extra):
    return [dict(trade_date=(start + timedelta(days=i)).strftime('%Y%m%d'),
                 close_price=c, open_price=c, high_price=c + 2, low_price=c - 2,
                 quantity=1000, turnover=c * 1000, trade_count=2, **extra)
            for i, c in enumerate(closes)]


@pytest.fixture
def source(monkeypatch):
    data = {'HMKB': history(range(100, 500))}
    calls = []
    monkeypatch.setattr(securities, 'get_securities_map', lambda: {
        ticker: {'isin': f'UZ{ticker}', 'type': 'bond' if ticker == 'BOND' else 'stock'} for ticker in data})
    def read(codes, days):
        calls.append((codes, days))
        return {f'UZ{t}': rows for t, rows in data.items() if f'UZ{t}' in codes}
    monkeypatch.setattr(quotes, 'get_quote_history', read)
    monkeypatch.setitem(api.app.dependency_overrides, access._require_user,
                        lambda: SimpleNamespace(id=1, email='admin@example.test', email_verified=True))
    monkeypatch.setattr(access, '_admin_role', lambda user: 'administrator')
    return data, calls, TestClient(api.app)


def fetch(source, ticker='HMKB'):
    response = source[2].get('/api/market/technical')
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    return response.json()['technical'][ticker]


def test_daily_metrics_have_explicit_dates_units_and_exact_windows(source):
    row = fetch(source)
    v = row['values']
    assert row['as_of'] == '2026-02-04'
    assert row['observations'] == 400
    assert v['sma20'] == pytest.approx((499 / 489.5 - 1) * 100)
    assert v['sma50'] == pytest.approx((499 / 474.5 - 1) * 100)
    assert v['sma200'] == pytest.approx((499 / 399.5 - 1) * 100)
    assert v['high52w'] == pytest.approx((499 / 501 - 1) * 100)
    assert v['low52w'] == pytest.approx((499 / 133 - 1) * 100)
    assert v['rsi14'] == 100
    assert v['atr14'] == 4
    assert v['changeOpen'] == 0
    assert v['gap'] == pytest.approx((499 / 498 - 1) * 100)
    assert v['dayChange'] == pytest.approx((499 / 498 - 1) * 100)
    assert v['dayVolume'] == 1000
    assert v['beta'] is None
    assert row['missing']['beta'] == 'benchmark_unavailable'
    assert len(source[1]) == 1


@pytest.mark.parametrize('closes, expected', [([100] * 15, 50), (list(range(100, 85, -1)), 0),
    ([44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28,46.00], 66.2496185536)])
def test_wilder_rsi_initialization_and_smoothing(source, closes, expected):
    source[0]['HMKB'] = history(closes)
    assert fetch(source)['values']['rsi14'] == pytest.approx(expected)


def test_missing_history_and_zero_volume_are_not_fabricated(source):
    source[0]['HMKB'] = history([100] * 14)
    source[0]['HMKB'][-1].update(open_price=None, high_price=None, low_price=None, quantity=0)
    row = fetch(source)
    for key in ['sma20', 'sma50', 'sma200', 'rsi14', 'high52w', 'low52w', 'atr14', 'changeOpen', 'gap']:
        assert row['values'][key] is None, key
        assert row['missing'][key]
    assert row['values']['dayVolume'] == 0
    assert row['values']['dayChange'] == 0


def test_bad_prices_do_not_compress_history_or_form_fictitious_ranges(source):
    source[0]['HMKB'] = history([100] * 30)
    source[0]['HMKB'][-5]['close_price'] = float('inf')
    source[0]['HMKB'][-1].update(high_price=90, low_price=110, open_price=0)
    row = fetch(source)
    for key in ['sma20', 'rsi14', 'atr14', 'changeOpen', 'gap']:
        assert row['values'][key] is None, key
    assert row['values']['dayChange'] == 0


def test_share_classes_keep_their_own_history_and_bonds_are_excluded(source):
    source[0].update(HMKBP=history([200] * 20), BOND=history([1000] * 30))
    body = source[2].get('/api/market/technical').json()
    assert 'BOND' not in body['technical']
    assert body['technical']['HMKBP']['values']['sma20'] == 0
    assert body['technical']['HMKB']['values']['sma20'] > 0
    assert 'UZBOND' not in source[1][0][0]


def test_alsm_recapitalization_adjusts_the_price_basis_before_calculation(source):
    # Real ALSM price and 2025 recapitalisation: 1,495 old UZS becomes 498.333…;
    # use 19 dated prior sessions to pin the SMA boundary around the real case.
    source[0].clear()
    rows = history([1495] * 19, start=date(2025, 4, 3))
    rows.append(dict(trade_date='20251007', close_price=897, open_price=890,
                     high_price=900, low_price=880, quantity=20))
    source[0]['ALSM'] = rows
    v = fetch(source, 'ALSM')['values']
    assert v['sma20'] == pytest.approx((897 / ((1495 / 3 * 19 + 897) / 20) - 1) * 100)
    assert v['dayChange'] == pytest.approx((897 / (1495 / 3) - 1) * 100)
    assert v['dayVolume'] == 20


def test_empty_and_invalid_dates_have_no_snapshot(source):
    source[0]['HMKB'] = [dict(trade_date='20260230', close_price=100), dict(trade_date='bad', close_price=200)]
    row = fetch(source)
    assert row['as_of'] is None
    assert all(value is None for value in row['values'].values())


@pytest.mark.parametrize('role', [None, 'analyst', 'auditor'])
def test_non_administrators_are_rejected_before_reading_quotes(source, monkeypatch, role):
    monkeypatch.setattr(access, '_admin_role', lambda user: role)
    response = source[2].get('/api/market/technical')
    assert response.status_code == 403
    assert source[1] == []


def test_anonymous_request_is_rejected(source, monkeypatch):
    monkeypatch.delitem(api.app.dependency_overrides, access._require_user)
    assert source[2].get('/api/market/technical').status_code == 401
    assert source[1] == []
