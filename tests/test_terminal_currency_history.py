from fastapi.testclient import TestClient
import pytest
import api
from server.currency import history


def test_archive_rate_is_dated_persisted_and_divided_by_nominal(monkeypatch,tmp_path):
    monkeypatch.setenv("CBU_HISTORY_DB", str(tmp_path/"fx.sqlite3"))
    calls=[]
    def fetch(day):
        calls.append(day)
        return [{"Ccy":"USD","Rate":"120000","Nominal":"10","Date":"30.12.2025"}]
    monkeypatch.setattr(history,"fetch",fetch)
    first=history.rates("2025-12-31")
    assert first["rates"][0]["per_unit"] == 12000
    assert first["rates"][0]["effective_date"] == "2025-12-30"
    assert history.rates("2025-12-31") == first
    assert calls == ["2025-12-31"]


def test_archive_never_substitutes_current_or_future_rate(monkeypatch,tmp_path):
    monkeypatch.setenv("CBU_HISTORY_DB", str(tmp_path/"fx.sqlite3"))
    monkeypatch.setattr(history,"fetch",lambda day:[{"Ccy":"USD","Rate":"13000","Nominal":"1","Date":"01.01.2026"}])
    with pytest.raises(ValueError):history.rates("2025-12-31")


def test_existing_currency_api_accepts_exact_historical_date(monkeypatch):
    monkeypatch.setattr(history,"rates",lambda day:{"ok":True,"as_of":day,"rates":[{"ccy":"USD","per_unit":12000}]})
    response=TestClient(api.app).get("/api/currency/rates?as_of=2025-12-31")
    assert response.json()["as_of"]=="2025-12-31"
    assert TestClient(api.app).get("/api/currency/rates?as_of=garbage").status_code==422


# Real CBU snapshots retain the bank's publication date and quoted nominal.
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

CBU_DAILY = json.loads(Path('tests/fixtures/cbu-daily-history.json').read_text())


def test_daily_series_includes_every_day_and_computes_real_month_change(monkeypatch):
    calls = []
    def daily(day):
        calls.append(day)
        raw = CBU_DAILY.get(day, CBU_DAILY['2026-10-24'])
        return {'rates': [{'ccy': r['Ccy'], 'per_unit': float(r['Rate']) / float(r['Nominal']),
                          'effective_date': min(day, '2026-10-24') if day not in CBU_DAILY else day} for r in raw]}
    monkeypatch.setattr(history, 'rates', daily)
    result = history.series('USD', 30, '2026-10-29')
    assert len(result['points']) == 31
    assert sorted(calls) == [(date(2026, 9, 29) + timedelta(days=i)).isoformat() for i in range(31)]
    assert result['points'][0]['value'] == 11806.97
    assert result['points'][-1]['value'] == 12004.02
    assert result['summary']['change'] == pytest.approx(197.05)
    assert result['summary']['change_pct'] == pytest.approx(197.05 / 11806.97 * 100)
    assert result['summary']['latest_date'] == '2026-10-29'
    assert result['missing_days'] == 0


def test_history_gap_is_not_filled_and_missing_boundary_has_no_period_return(monkeypatch):
    def daily(day):
        if day in {'2026-10-22', '2026-10-25'}: raise RuntimeError('Archive unavailable')
        return {'rates': [{'ccy': 'RUB', 'per_unit': 148.8, 'effective_date': min(day, '2026-10-28')}]}
    monkeypatch.setattr(history, 'rates', daily)
    result = history.series('RUB', 7, '2026-10-29')
    assert result['points'][0]['value'] is None
    assert result['points'][3]['value'] is None
    assert result['points'][-1]['effective_date'] == '2026-10-28'
    assert result['summary']['change'] is None
    assert result['summary']['change_pct'] is None
    assert result['missing_days'] == 2


def test_history_endpoint_validates_ranges_and_reports_total_outage(monkeypatch):
    monkeypatch.setattr(history, 'rates', lambda day: (_ for _ in ()).throw(RuntimeError('down')))
    client = TestClient(api.app)
    assert client.get('/api/currency/history?ccy=USD&days=7&end=2026-10-29').status_code == 503
    for query in ('ccy=BTC', 'days=9999', 'days=1', 'end=2099-01-01', 'end=1999-01-01'):
        assert client.get('/api/currency/history?' + query).status_code == 422


def test_current_day_archive_refreshes_without_discarding_historical_cache(monkeypatch, tmp_path):
    monkeypatch.setenv('CBU_HISTORY_DB', str(tmp_path / 'fx.sqlite3'))
    monkeypatch.setattr(history, '_today', lambda: date(2026, 10, 29), raising=False)
    clock = SimpleNamespace(now=100000)
    monkeypatch.setattr(history, 'time', SimpleNamespace(time=lambda: clock.now), raising=False)
    calls = []
    monkeypatch.setattr(history, 'fetch', lambda day: calls.append(day) or CBU_DAILY[day])
    history.rates('2026-10-29')
    history.rates('2026-09-29')
    history.rates('2026-10-29')
    clock.now += 1801
    history.rates('2026-10-29')
    history.rates('2026-09-29')
    assert calls == ['2026-10-29', '2026-09-29', '2026-10-29']


def test_cold_range_stops_starting_requests_after_budget(monkeypatch):
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(history, 'time', SimpleNamespace(monotonic=lambda: clock.now), raising=False)
    monkeypatch.setattr(history, '_pool', SimpleNamespace(map=lambda fn, days: map(fn, days)), raising=False)
    calls = []
    def daily(day, *, fetch_missing=True):
        if not fetch_missing: raise LookupError('No cached snapshot')
        calls.append(day)
        clock.now += 10
        return {'rates': [{'ccy':'USD', 'per_unit':12004.02, 'effective_date':day}]}
    monkeypatch.setattr(history, 'rates', daily)
    result = history.series('USD', 180, '2026-10-29')
    assert len(calls) == 3
    assert result['missing_days'] == 178
    assert result['pending_days'] == 178
    assert calls[:2] == ['2026-05-02', '2026-10-29']
    assert result['summary']['change'] == 0


def test_snapshot_taken_during_publication_day_is_finalized_after_midnight(monkeypatch, tmp_path):
    monkeypatch.setenv('CBU_HISTORY_DB', str(tmp_path / 'fx.sqlite3'))
    clock = SimpleNamespace(day=date(2026, 10, 29))
    monkeypatch.setattr(history, '_today', lambda: clock.day)
    calls = []
    monkeypatch.setattr(history, 'fetch', lambda day: calls.append(day) or CBU_DAILY[day])
    history.rates('2026-10-29')
    clock.day = date(2026, 10, 30)
    history.rates('2026-10-29')
    history.rates('2026-10-29')
    assert calls == ['2026-10-29', '2026-10-29']


def test_expired_range_budget_still_serves_cached_recent_observations(monkeypatch, tmp_path):
    monkeypatch.setenv('CBU_HISTORY_DB', str(tmp_path / 'fx.sqlite3'))
    monkeypatch.setattr(history, 'fetch', lambda day: CBU_DAILY[day])
    history.rates('2026-10-28')
    # No network budget remains; only the persisted observation may be returned.
    ticks = iter([0, *([31] * 8)])
    monkeypatch.setattr(history, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(history, '_pool', SimpleNamespace(map=lambda fn, days: map(fn, days)))
    monkeypatch.setattr(history, 'fetch', lambda day: pytest.fail('Network after deadline'))
    result = history.series('USD', 7, '2026-10-29')
    assert result['summary']['latest'] == 11918.98
    assert result['summary']['latest_date'] == '2026-10-28'
    assert result['missing_days'] == 7
