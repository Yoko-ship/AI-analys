"""IPTB 2026Q3: OpenInfo replaced a zero-filled workbook at the same URL.

Real old/new parsed source cells captured on 2026-10-21. Source amounts are
thousands of UZS; the cache must follow collection, including other issuers.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from collectors.openinfo import cache, settings, spreadsheets, workbooks
import catalogue.history as history


@pytest.fixture
def source(monkeypatch, tmp_path):
    data = json.loads(Path('tests/fixtures/openinfo/iptb_2026q3_replaced.json').read_text())
    monkeypatch.setattr(settings, 'EXCEL_CACHE_PATH', tmp_path / 'cache.json')
    monkeypatch.setattr(cache, '_EXCEL_CACHE_MEMO', None)
    monkeypatch.setattr(settings, 'EXCEL_CACHE_TTL_SECONDS', 30 * 86400)
    monkeypatch.setattr(workbooks, '_parse_excel_workbook', lambda content: deepcopy(data['current']))
    return data


def session_for(content=b'new-workbook', error=None):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if error:
            raise error
        return SimpleNamespace(content=content, headers={}, raise_for_status=lambda: None)
    return SimpleNamespace(get=get), calls


def loan(payload):
    return next(r for r in payload['sheets'][0]['table_rows'] if r['row'] == 48)['numeric_values'][-1]


def test_iptb_collected_revision_replaces_zero_filled_cache(source):
    cache._set_excel_cache(source['url'], {**source['cached'], 'financial_revision': 'old'})
    session, calls = session_for()
    result = spreadsheets.parse_excel_report_document(session, {
        'excel_url': source['url'], 'financial_revision': 'current-2072293767',
    })
    assert loan(result) == 36_754_304_013
    assert calls == [source['url']]
    assert result['content_sha256'] == hashlib.sha256(b'new-workbook').hexdigest()
    assert loan(cache._get_excel_cache(source['url'])) == 36_754_304_013


def test_unchanged_financial_revision_uses_cache(source):
    cache._set_excel_cache(source['url'], {**source['current'], 'financial_revision': 'same'})
    session, calls = session_for(error=AssertionError('unchanged filing must use cache'))
    result = spreadsheets.parse_excel_report_document(session, {'excel_url': source['url'], 'financial_revision': 'same'})
    assert loan(result) == 36_754_304_013
    assert calls == []


def test_collector_refresh_updates_existing_report_cache(source):
    cache._set_excel_cache(source['url'], source['cached'])
    session, calls = session_for()
    history._parse_workbook_uncached(session, source['url'])
    assert loan(cache._get_excel_cache(source['url'])) == 36_754_304_013
    assert calls == [source['url']]


def test_bulk_history_does_not_fill_cache_with_every_old_workbook(source):
    session, _ = session_for()
    history._parse_workbook_uncached(session, source['url'])
    assert cache._get_excel_cache(source['url']) is None


def test_incomplete_report_retry_is_bounded_even_if_source_stays_incomplete(source, monkeypatch):
    monkeypatch.setattr(workbooks, '_parse_excel_workbook', lambda content: deepcopy(source['cached']))
    cache._set_excel_cache(source['url'], source['cached'])
    session, calls = session_for()
    for _ in range(3):
        spreadsheets.parse_excel_report_document(session, {'excel_url': source['url']}, revalidate_cached=True)
    assert calls == [source['url']]


def test_failed_refresh_keeps_last_workbook_and_does_not_hammer_source(source):
    cache._set_excel_cache(source['url'], {**source['current'], 'financial_revision': 'old'})
    session, calls = session_for(error=TimeoutError('source timeout'))
    for _ in range(3):
        result = spreadsheets.parse_excel_report_document(session, {
            'excel_url': source['url'], 'financial_revision': 'new',
        })
        assert loan(result) == 36_754_304_013
        assert result['refresh_failed'] is True
    assert calls == [source['url']]


def test_changed_content_hash_changes_after_revalidation(source):
    cache._set_excel_cache(source['url'], {**source['current'], 'content_sha256': 'old-hash'})
    session, _ = session_for(content=b'revised-source')
    result = spreadsheets.parse_excel_report_document(session, {'excel_url': source['url']}, revalidate_cached=True)
    assert result['content_sha256'] == hashlib.sha256(b'revised-source').hexdigest()


def test_catalogue_revision_tracks_values_not_collection_time(source, monkeypatch, tmp_path):
    import catalogue.storage as storage
    import catalogue.sources as sources
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    c = storage.get_catalog_conn()
    c.execute("INSERT INTO catalog_financials(ticker,form,year,quarter,net_income,updated_at) VALUES ('IPTB','NSBU',2026,3,0,'2026-10-20')")
    c.commit()
    monkeypatch.setattr(sources.catalogue_filings, 'get_report_urls', lambda *a: {'excel_url': source['url']})
    session, calls = session_for()
    monkeypatch.setattr(sources, '_make_session', lambda: session)
    sources.fetch_report_excel_data('IPTB', 'NSBU', 2026, 3)
    c.execute("UPDATE catalog_financials SET updated_at='2026-10-21'"); c.commit()
    sources.fetch_report_excel_data('IPTB', 'NSBU', 2026, 3)
    assert len(calls) == 1
    c.execute('UPDATE catalog_financials SET net_income=2072293767'); c.commit()
    sources.fetch_report_excel_data('IPTB', 'NSBU', 2026, 3)
    assert len(calls) == 2, 'a changed filing must revalidate the workbook at the same URL'
    c.close()


def setup_iptb_report(monkeypatch, source, fetch):
    from datetime import datetime, timezone
    import issuer_financials as financials
    import sector_report_service as service
    issuer = {'id': '17', 'ticker': 'IPTB', 'name': 'Ipoteka-bank', 'oked_code': '64190'}
    snapshot = {
        'organization_type': 'bank', 'standard': 'nsbu', 'scope': 'separate',
        'period': '2026Q3', 'period_basis': 'cumulative_ytd', 'previous_comparable_period': '2025Q3',
        'current_values': {'total_assets': 58532913619, 'total_equity': 9265131323,
                           'total_liabilities': 49267782296, 'net_income': 2072293767,
                           'cash': 907837063, 'operating_expenses': 1732361785},
        'opening_values': {'total_assets': 54728498246, 'total_equity': 7734691283,
                           'total_liabilities': 46993806963},
        'previous_values': {'net_income': 102523946, 'operating_expenses': 1303780017},
        'source': {'url': 'https://openinfo.uz/ru/reports/to_pdf31481/'},
        'quality': {'traceable': True, 'verification_status': 'verified', 'data_quality': []},
    }
    monkeypatch.setattr(financials, 'classify_organization', lambda *a: 'bank')
    monkeypatch.setattr(financials, 'financial_snapshot', lambda *a: deepcopy(snapshot))
    monkeypatch.setattr(financials, 'report_rows', lambda *a: [{'period': '2026Q3', 'excel_url': source['url']}])
    monkeypatch.setattr(financials, 'fetch_report_excel_data', fetch)
    monkeypatch.setattr(financials, 'quote_and_trade', lambda *a: ({}, {}))
    monkeypatch.setattr(financials, 'now', lambda: datetime(2026, 10, 21, tzinfo=timezone.utc))
    monkeypatch.setattr(service, '_REPORT_CACHE', {})
    return service, issuer


def test_iptb_shortened_report_retries_cached_workbook_and_recovers_bank_lines(source, monkeypatch):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(kwargs)
        p = deepcopy(source['current' if kwargs.get('revalidate_cached') else 'cached'])
        p['from_cache'] = not kwargs.get('revalidate_cached', False)
        return {'ok': True, 'income': p, 'balance': p}
    service, issuer = setup_iptb_report(monkeypatch, source, fetch)
    report = service.sector_report(issuer, 'nsbu', '2026Q3', 'separate', 'ru', persist=False)
    assert report['content_status'] == 'complete'
    assert not any(q['code'] == 'KEY_LINE_MISSING' for q in report['data_quality'])
    facts = {f['metric_code']: f['value'] for f in report['verified_facts']}
    assert facts['loan_portfolio'] == 36754304013
    assert facts['interest_income'] == 9447836814
    assert facts['customer_funds'] == 29321578637
    assert len(calls) == 2


def test_failed_refresh_does_not_replace_last_verified_publication(monkeypatch, tmp_path):
    from reporting import store
    monkeypatch.setenv('SECTOR_ANALYSIS_DB', str(tmp_path / 'reports.db'))
    prior = {'version': 'verified-iptb', 'issuer': {'id': '17', 'ticker': 'IPTB'},
             'language': 'ru', 'standard': 'nsbu', 'period': '2026Q3', 'status': 'available',
             'financial_as_of': '2026-09-30', 'availability': {}, 'headline': 'Verified bank report',
             'content_status': 'complete', 'data_quality': []}
    store.record_report(deepcopy(prior))
    failed = {**prior, 'version': 'stale-source-attempt', 'source_refresh_failed': True,
              'content_status': 'shortened', 'headline': 'Incomplete report',
              'data_quality': [{'code': 'SOURCE_REFRESH_FAILED', 'severity': 'warning'}]}
    shown = store.record_report(failed)
    assert shown['version'] == 'verified-iptb'
    assert shown['source_refresh_failed'] is True
    assert any(q['code'] == 'SOURCE_REFRESH_FAILED' for q in shown['data_quality'])
    assert store.latest_publication('17', 'ru', 'nsbu')['version'] == 'verified-iptb'


def test_first_report_with_failed_refresh_is_not_published_as_verified(monkeypatch, tmp_path):
    from reporting import store
    monkeypatch.setenv('SECTOR_ANALYSIS_DB', str(tmp_path / 'reports.db'))
    report = {'version': 'unverified-refresh', 'issuer': {'id': '17', 'ticker': 'IPTB'},
              'language': 'ru', 'standard': 'nsbu', 'period': '2026Q3', 'status': 'available',
              'financial_as_of': '2026-09-30', 'availability': {}, 'source_refresh_failed': True}
    stored = store.record_report(report)
    assert stored['status'] == 'stale'
    assert store.latest_publication('17', 'ru', 'nsbu') is None


def test_report_worker_retries_failed_refresh_instead_of_marking_success(monkeypatch):
    from reporting import worker
    finished = []
    monkeypatch.setattr(worker.store, 'due_jobs', lambda limit: [{'id': 'job', 'ticker': 'IPTB', 'attempts': 0}])
    monkeypatch.setattr(worker.store, 'claim_job', lambda key: True)
    monkeypatch.setattr(worker.store, 'finish_job', lambda *args: finished.append(args))
    monkeypatch.setattr(worker.financials, 'resolve_issuer', lambda ticker: {'ticker': ticker})
    monkeypatch.setattr(worker.sector_report_service, 'sector_report', lambda *args: {
        'status': 'available', 'source_refresh_failed': True,
        'data_quality': [{'code': 'SOURCE_REFRESH_FAILED', 'severity': 'warning'}],
    })
    worker.run_pending()
    assert finished == [('job', 'retry', 1, 'SOURCE_REFRESH_FAILED')]


def test_refresh_retry_waits_for_source_cooldown(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from reporting import store
    monkeypatch.setenv('SECTOR_ANALYSIS_DB', str(tmp_path / 'reports.db'))
    monkeypatch.setattr(store, 'now', lambda: '2026-10-21T10:00:00+00:00')
    job = store.enqueue('IPTB', 'changed-source')
    before = datetime.now(timezone.utc)
    store.finish_job(job, 'retry', 1, 'SOURCE_REFRESH_FAILED')
    with store.connect() as c:
        row = c.execute('SELECT next_attempt FROM sector_jobs WHERE id=?', (job,)).fetchone()
    assert (datetime.fromisoformat(row['next_attempt']) - before).total_seconds() >= 3600


def test_healthy_cached_report_is_not_downloaded_again(source, monkeypatch):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(kwargs)
        p = {**deepcopy(source['current']), 'from_cache': True}
        return {'ok': True, 'income': p, 'balance': p}
    service, issuer = setup_iptb_report(monkeypatch, source, fetch)
    report = service.sector_report(issuer, 'nsbu', '2026Q3', 'separate', 'ru', persist=False)
    assert report['content_status'] == 'complete'
    assert calls == [{}]


def test_unvb_live_filing_really_has_no_current_loan_book():
    """Negative control: refreshing cannot manufacture what a source omits."""
    import sector_report_service as service
    data = json.loads(Path('tests/fixtures/openinfo/unvb_2026q3_incomplete.json').read_text())
    p = data['current']
    rows = {r['row']: r for r in p['sheets'][0]['table_rows']}
    assert rows[48]['numeric_values'][-1] == 0
    snapshot = {'current_values': {'total_assets': rows[65]['numeric_values'][-1]},
                'opening_values': {}, 'previous_values': {}}
    service.map_special_lines(snapshot, {'income': p, 'balance': p}, 'bank')
    assert snapshot['current_values'].get('loan_portfolio') == 0, 'do not copy the opening loan book into the missing current column'


def test_failed_first_attempt_cannot_poison_later_publication_version(monkeypatch, tmp_path):
    from reporting import store
    monkeypatch.setenv('SECTOR_ANALYSIS_DB', str(tmp_path / 'reports.db'))
    report = {'version': 'same-financial-facts', 'issuer': {'id': '17', 'ticker': 'IPTB'},
              'language': 'ru', 'standard': 'nsbu', 'period': '2026Q3', 'status': 'available',
              'financial_as_of': '2026-09-30', 'availability': {}}
    store.record_report({**deepcopy(report), 'source_refresh_failed': True})
    store.record_report(deepcopy(report))
    latest = store.latest_publication('17', 'ru', 'nsbu')
    assert latest['status'] == 'available'
    assert not latest.get('source_refresh_failed')
