"""Page reads must not wait for OpenInfo downloads or source revalidation."""
from copy import deepcopy

import pytest

import catalogue.sources as sources
import issuer_analysis_api as api
import sector_report_service as service
from reporting import reads, store, worker


@pytest.mark.parametrize('ticker', ['HMKB', 'SQBN', 'UZTL', 'ODMP'])
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
    assert calls == [(ticker, 'NSBU', 2025, 0)] * (2 if pending else 1)
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


@pytest.fixture
def ready_report(monkeypatch):
    calls = []
    def prepare(issuer, standard, period, scope, lang, **kwargs):
        calls.append((deepcopy(issuer), standard, period, scope, lang))
        return {'status': 'available', 'period': period or '2026Q3',
                'ratios': [{'metric_code': 'ebit', 'value': -288401.4}]}
    monkeypatch.setattr(service, 'sector_report', prepare)
    monkeypatch.setattr(service, 'public_report', deepcopy)
    return calls


def test_odmp_repeat_read_reuses_completed_response_without_sharing_mutable_data(ready_report):
    issuer = {'id': '538', 'ticker': 'ODMP'}
    first = reads.read_report(issuer, 'nsbu', None, 'separate', 'ru')
    first['ratios'][0]['value'] = 0
    second = reads.read_report(issuer, 'nsbu', None, 'separate', 'ru')
    assert second['ratios'][0]['value'] == -288401.4
    assert len(ready_report) == 1


@pytest.mark.parametrize('changed', ['ticker', 'isin', 'standard', 'period', 'scope', 'lang'])
def test_ready_report_keeps_request_context_separate(ready_report, changed):
    issuer = {'id': '538', 'ticker': 'ODMP', 'isin': 'ordinary'}
    context = dict(standard='nsbu', period=None, scope='separate', lang='ru')
    reads.read_report(issuer, **context)
    if changed in issuer:
        issuer[changed] = 'preferred'
    else:
        context[changed] = {'standard': 'ifrs', 'period': '2025', 'scope': 'consolidated', 'lang': 'en'}[changed]
    reads.read_report(issuer, **context)
    assert len(ready_report) == 2


def test_ready_report_expires_without_sleep(monkeypatch, ready_report):
    from reporting import read_cache
    clock = [100.0]
    monkeypatch.setattr(read_cache, 'monotonic', lambda: clock[0])
    issuer = {'id': '538', 'ticker': 'ODMP'}
    reads.read_report(issuer, 'nsbu', None, 'separate', 'ru')
    clock[0] += 301
    reads.read_report(issuer, 'nsbu', None, 'separate', 'ru')
    assert len(ready_report) == 2


def test_ready_report_uses_the_reporting_clock_at_day_boundary(monkeypatch, ready_report):
    from datetime import datetime, timezone
    import issuer_financials
    issuer = {'id': '538', 'ticker': 'ODMP'}
    for day in (28, 29):
        monkeypatch.setattr(issuer_financials, 'now', lambda: datetime(2026, 11, day, tzinfo=timezone.utc))
        reads.read_report(issuer, 'nsbu', None, 'separate', 'ru')
    assert len(ready_report) == 2


@pytest.mark.parametrize('changed', ['catalog', 'securities', 'workbook', 'config', 'hold', 'rule', 'override'])
def test_ready_report_invalidates_changed_inputs(monkeypatch, tmp_path, ready_report, changed):
    import json
    import sqlite3
    import securities_catalog
    from admin_control import store as admin
    from collectors.openinfo import settings
    from reporting import read_cache
    catalog = tmp_path / 'catalog.db'
    securities = tmp_path / 'securities.db'
    workbook = tmp_path / 'workbooks.json'
    config = tmp_path / 'config'
    config.mkdir()
    reviewed = config / 'reviewed.json'
    reviewed.write_text('[]')
    workbook.write_text('{}')
    monkeypatch.setenv('CATALOG_DB_PATH', str(catalog))
    monkeypatch.setenv('ADMIN_CONTROL_DB', str(tmp_path / 'admin.db'))
    monkeypatch.setattr(securities_catalog, 'DB_PATH', securities)
    monkeypatch.setattr(settings, 'EXCEL_CACHE_PATH', workbook)
    monkeypatch.setattr(read_cache, 'CONFIG_DIR', config)
    connections = [sqlite3.connect(path) for path in (catalog, securities)]
    try:
        for connection in connections:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('CREATE TABLE sample (value INTEGER)')
            connection.commit()
        issuer = {'id': '538', 'ticker': 'ODMP'}
        reads.read_report(issuer, 'nsbu', None, 'separate', 'ru')
        if changed in ('catalog', 'securities'):
            connection = connections[int(changed == 'securities')]
            connection.execute('INSERT INTO sample VALUES (1)')
            connection.commit()
        elif changed == 'workbook':
            workbook.write_text('{"updated":true}')
        elif changed == 'config':
            reviewed.write_text('[{"updated":true}]')
        elif changed == 'hold':
            with store.connect() as connection:
                connection.execute('INSERT INTO sector_publication_holds VALUES (?,?,?,?,?)',
                                   ('538', 'ru', 'nsbu', 'restored', 'rejected'))
        elif changed == 'rule':
            with admin.connection(write=True) as connection:
                connection.execute('INSERT INTO control_resources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (admin.environment(), 'rules', 'r1', '', 'ACTIVE', '', '', '', '', '', 1, '', '', json.dumps({'id': 'r1'})))
        else:
            with store.connect() as connection:
                connection.execute('INSERT INTO sector_overrides VALUES (?,?,?,?,?,?,?)',
                    ('v1', '538', 'ODMP', '2026-01-01', '2026-12-31', '{}', '2026-01-01'))
        reads.read_report(issuer, 'nsbu', None, 'separate', 'ru')
        assert len(ready_report) == 2
    finally:
        for connection in connections:
            connection.close()


def test_response_is_not_cached_if_source_changes_during_preparation(monkeypatch, ready_report):
    from reporting import read_cache
    revisions = iter(['before', 'after', 'after', 'after', 'after'])
    monkeypatch.setattr(read_cache, '_revision', lambda *args: next(revisions))
    issuer = {'id': '538', 'ticker': 'ODMP'}
    for _ in range(3):
        reads.read_report(issuer, 'nsbu', None, 'separate', 'ru')
    assert len(ready_report) == 2


def test_failed_preparation_can_be_retried(monkeypatch, ready_report):
    def failed(*args, **kwargs):
        raise ValueError('invalid source')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'public_report', failed)
        with pytest.raises(ValueError, match='invalid source'):
            reads.read_report({'id': '538', 'ticker': 'ODMP'}, 'nsbu', None, 'separate', 'ru')
    reads.read_report({'id': '538', 'ticker': 'ODMP'}, 'nsbu', None, 'separate', 'ru')
    assert len(ready_report) == 2


def test_concurrent_odmp_readers_share_one_preparation(monkeypatch, ready_report):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release = Event(), Event()
    def project(report):
        entered.set()
        assert release.wait(5)
        return deepcopy(report)
    monkeypatch.setattr(service, 'public_report', project)
    def read():
        return reads.read_report({'id': '538', 'ticker': 'ODMP'}, 'nsbu', None, 'separate', 'ru')
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(read)
        assert entered.wait(5)
        second = pool.submit(read)
        release.set()
        assert first.result() == second.result()
    assert len(ready_report) == 1


def test_postgres_reads_bypass_file_revision_cache(monkeypatch, ready_report):
    import dbx
    monkeypatch.setattr(dbx, 'backend', lambda: dbx.POSTGRES)
    for _ in range(2):
        reads.read_report({'id': '538', 'ticker': 'ODMP'}, 'nsbu', None, 'separate', 'ru')
    assert len(ready_report) == 2
