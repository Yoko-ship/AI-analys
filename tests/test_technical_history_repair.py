"""Repair real incomplete histories without changing known prices or inventing trades."""
import importlib
import json
from pathlib import Path

import pytest

import catalogue.market_store as quotes
import securities_catalog as securities
from collectors.openinfo import transport
from technical_screener import snapshot


@pytest.fixture
def source(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_BACKEND', 'sqlite')
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    data = json.loads((Path(__file__).parent / 'fixtures/technical_atr_recovery.json').read_text())
    universe = {t: {'isin': d['isin'], 'type': 'stock'} for t, d in data.items()}
    universe['ODMP'] = {'isin': '', 'type': 'stock'}
    monkeypatch.setattr(securities, 'get_securities_map', lambda: universe)
    for d in data.values():
        quotes.bulk_upsert_quote_history(d['stored'])
    requests = []
    def fetch(session, path, params):
        assert path == '/iuzse/conclusions/'
        assert params['isu_cd'], 'An empty ISIN returns the whole exchange, not this issuer'
        requests.append(params)
        return next(d['archive'] for d in data.values() if d['isin'] == params['isu_cd'])
    monkeypatch.setattr(transport, '_json_get', fetch)
    return data, requests


def repair(**kwargs):
    module = importlib.import_module('catalogue.technical_history')
    return module.repair(**kwargs)


def test_real_archive_recovery_is_previewable_idempotent_and_preserves_known_prices(source):
    data, requests = source
    codes = [d['isin'] for d in data.values()]
    before = quotes.get_quote_history(codes, 600)
    preview = repair()
    assert quotes.get_quote_history(codes, 600) == before
    assert {r['ticker'] for r in preview if r['status'] == 'recoverable'} == set(data)
    assert next(r for r in preview if r['ticker'] == 'ODMP')['status'] == 'missing_isin'
    applied = repair(apply=True)
    assert {r['ticker'] for r in applied if r['status'] == 'recovered'} == set(data)
    after = quotes.get_quote_history(codes, 600)
    # OCBK has two contradictory official conclusions on 2024-04-08 and no
    # independent stored price. Preserve that unknown session so Wilder's
    # smoothing cannot silently cross it after the repair is persisted.
    conflict = [r for r in after[data['OCBK']['isin']] if r['trade_date'] == '20240408']
    assert len(conflict) == 1
    assert all(conflict[0][k] is None for k in ['close_price', 'high_price', 'low_price'])
    for code, rows in after.items():
        assert snapshot(rows)['values']['atr14'] is not None
        old = {r['trade_date']: r for r in before[code]}
        for row in rows:
            for field in ['close_price', 'open_price', 'high_price', 'low_price', 'quantity', 'turnover']:
                value = old.get(row['trade_date'], {}).get(field)
                if value is not None:
                    assert row[field] == value
    count = len(requests)
    repair(apply=True)
    assert len(requests) == count, 'Do not refetch complete histories'
    assert quotes.get_quote_history(codes, 600) == after


def test_wrong_security_and_source_failure_never_write_history(source, monkeypatch):
    data, _ = source
    data['KSCMP']['archive']['ticker'] = 'OTHER'
    data['OCBK']['archive']['results'] = []
    fetch = transport._json_get
    def unavailable(session, path, params):
        if params['isu_cd'] == data['YGSY']['isin']:
            raise RuntimeError('Source unavailable')
        return fetch(session, path, params)
    monkeypatch.setattr(transport, '_json_get', unavailable)
    before = quotes.get_quote_history([d['isin'] for d in data.values()], 600)
    result = repair(apply=True)
    assert next(r for r in result if r['ticker'] == 'KSCMP')['status'] == 'source_mismatch'
    assert all(r['status'] != 'recovered' for r in result)
    assert quotes.get_quote_history(list(before), 600) == before


@pytest.fixture
def executions(source, monkeypatch):
    data = json.loads((Path(__file__).parent / 'fixtures/technical_atr_executions.json').read_text())
    monkeypatch.setattr(securities, 'get_securities_map', lambda: {
        t: {'isin': d['isin'], 'type': 'stock'} for t, d in data.items()})
    for d in data.values():
        quotes.bulk_upsert_quote_history(d['stored'])
    requests = []
    def fetch(session, path, params):
        requests.append((path, dict(params)))
        d = next(d for d in data.values() if d['isin'] == params['isu_cd'])
        return d['archive'] if path == '/iuzse/conclusions/' else d['executions']
    monkeypatch.setattr(transport, '_json_get', fetch)
    return data, requests


def test_orgs_missing_daily_summary_is_recovered_from_openinfo_executions(executions):
    data, requests = executions
    result = {r['ticker']: r for r in repair(apply=True)}
    assert result['ORGS']['status'] == 'recovered'
    assert result['ORGS']['observations'] == 14
    rows = quotes.get_quote_history([data['ORGS']['isin']], 600)[data['ORGS']['isin']]
    recovered = next(r for r in rows if r['trade_date'] == '20231220')
    assert recovered['close_price'] == 32684.69
    assert recovered['high_price'] == recovered['low_price'] == 32684.69
    assert snapshot(rows)['values']['atr14'] == pytest.approx(4983.527142857143)
    # The 2026-09-29 T1 block is not an order-book session, despite matching
    # the same ticker. Its large negotiated price must never enter ATR.
    assert not any(r['trade_date'] == '20260929' for r in rows)
    assert result['IPKYP']['status'] == 'insufficient_history'
    assert result['IPKYP']['observations'] == 1
    # Its ninth G1 date is on FCT, not the stock market, so exclude it too.
    assert result['INFB']['observations'] == 8
    assert result['INFB']['status'] == 'insufficient_history'
    assert any(path == '/iuzse/trade-results/' for path, _ in requests)


@pytest.mark.parametrize('fault', ['short_page', 'wrong_isin', 'wrong_date', 'ambiguous_close'])
def test_execution_repair_rejects_incomplete_or_unverifiable_prices(executions, fault):
    data, _ = executions
    payload = data['ORGS']['executions']
    row = next(r for r in payload['results'] if r['trade_datetime'].startswith('2023-12-20'))
    if fault == 'short_page':
        payload['results'].pop()
    elif fault == 'wrong_isin':
        row['isin_code'] = data['INFB']['isin']
    elif fault == 'wrong_date':
        row['trade_datetime'] = '2000-12-20T11:08:07'
    else:
        payload['results'].append({**row, 'trade_price': 33000})
        payload['count'] += 1
    before = quotes.get_quote_history([data['ORGS']['isin']], 600)
    result = next(r for r in repair(apply=True) if r['ticker'] == 'ORGS')
    assert result['status'] != 'recovered'
    assert quotes.get_quote_history(list(before), 600) == before


@pytest.mark.parametrize('changing', [False, True])
def test_execution_history_follows_actual_page_size_and_rechecks_stability(executions, monkeypatch, changing):
    data, _ = executions
    fetch = transport._json_get
    first_reads = 0
    def paged(session, path, params):
        nonlocal first_reads
        if path != '/iuzse/trade-results/' or params['isu_cd'] != data['ORGS']['isin']:
            return fetch(session, path, params)
        payload = data['ORGS']['executions']
        rows = payload['results']
        page, size = params['page'], 7
        pages = (len(rows) + size - 1) // size
        if page == 1:
            first_reads += 1
        return {**payload, 'count': len(rows) + int(changing and first_reads > 1),
                'page_size': size, 'total_pages': pages, 'current_page': page,
                'has_next': page < pages, 'results': rows[(page-1)*size:page*size]}
    monkeypatch.setattr(transport, '_json_get', paged)
    result = next(r for r in repair(apply=True) if r['ticker'] == 'ORGS')
    assert result['status'] == ('source_error' if changing else 'recovered')
    assert first_reads == 2
