"""Page reads must not wait for OpenInfo downloads or source revalidation."""
from copy import deepcopy

import pytest

import catalogue.sources as sources
import issuer_analysis_api as api
import sector_report_service as service
from reporting import store, worker


@pytest.mark.parametrize('ticker', ['HMKB', 'SQBN', 'UZTL'])
@pytest.mark.parametrize('pending', [False, True])
def test_ratios_read_saved_sources_and_queue_missing_detail(monkeypatch, ticker, pending):
    issuer = {'id': '8', 'ticker': ticker}
    calls = []
    def saved(*args):
        calls.append(args)
        return {'ok': not pending}
    monkeypatch.setattr(sources, 'cached_report_excel_data', saved)
    def report(*args, source_reader=None, **kwargs):
        assert source_reader is not None, 'Public report still downloads source workbooks'
        workbook = source_reader(ticker, 'NSBU', 2025, 0)
        return {'status': 'stale' if pending else 'available', 'period': '2025',
                'source_refresh_failed': not workbook['ok'], 'ratios': [], 'data_quality': []}
    monkeypatch.setattr(service, 'sector_report', report)
    monkeypatch.setattr(service, 'public_report', deepcopy)
    for _ in range(2):
        result = api._sector_ai_report(issuer, 'nsbu', '2025', 'separate', 'en')
        assert result['status'] == ('stale' if pending else 'available')
    assert calls == [(ticker, 'NSBU', 2025, 0)] * 2
    jobs = store.due_jobs(10)
    assert len(jobs) == int(pending)
    if pending:
        assert jobs[0]['ticker'] == ticker
        seen = []
        monkeypatch.setattr(worker.financials, 'resolve_issuer', lambda _: issuer)
        def refreshed(*args, **kwargs):
            seen.append((args, kwargs))
            return {'status': 'available', 'data_quality': []}
        monkeypatch.setattr(service, 'sector_report', refreshed)
        assert worker.run_pending() == 1
        assert seen == [((issuer, 'nsbu', '2025', 'separate', 'en'), {})]
        assert store.due_jobs(10) == []
