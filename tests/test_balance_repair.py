"""A real UZAS filing repairs source data without erasing reviewed decisions."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import data_quality as dq
from catalogue import balance_repair, financial_store, filings, sources, storage

FILING = json.loads((Path(__file__).parent / 'fixtures/sector_v22_filings.json').read_text(encoding='utf-8'))['UZAS']


@pytest.fixture
def source(monkeypatch, tmp_path):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    financial_store.bulk_upsert_financials([{'ticker': 'UZAS', 'year': 2026, 'quarter': 2,
        'org_type': 'insurance', 'net_income': 294295.9, 'revenue': 111891908.5,
        'total_assets': 332548245.7, 'total_equity': 147661927.4, 'total_liabilities': 80360618.0}])
    monkeypatch.setattr(filings, 'get_report_urls', lambda *_: {
        'excel_url': 'https://openinfo.uz/uzas-2026q2.xlsx', 'published_at': '2026-07-30'})
    monkeypatch.setattr(sources, 'fetch_report_excel_data', lambda *_: {'ok': True, **deepcopy(FILING['workbook'])})
    return tmp_path


def correction(reason, field='total_assets', value=228022545.4):
    return dq.apply_correction({'ticker': 'UZAS', 'form': 'NSBU', 'year': 2026, 'quarter': 2,
        'field': field, 'value_thousands_uzs': value, 'source_url': 'https://openinfo.uz/uzas-2026q2.xlsx',
        'source_reference': 'UZAS 2026 H1', 'reason': reason}, 'reviewer@example.test')


def test_preview_then_verified_repair_is_audited_and_idempotent(source):
    bad = correction('Автоматическая подсказка по формуле: Assets = equity + liabilities.')
    manual = correction('Verified manually against the signed filing', 'net_income', 0)
    preview = balance_repair.repair(tickers=['UZAS'], apply=False, backup_dir=source / 'backup')
    assert preview['changed'] == 0
    assert preview['plans'][0]['revert_correction_ids'] == [bad['id']]
    assert dq.approved_corrections_for('UZAS', 'NSBU', 2026, 2)['total_assets'] == 228022545.4
    result = balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=source / 'backup')
    assert result['changed'] == 1
    assert list((source / 'backup').glob('*.json'))
    assert dq.approved_corrections_for('UZAS', 'NSBU', 2026, 2) == {'net_income': 0}
    conn = storage.get_catalog_conn()
    try:
        row = conn.execute("SELECT * FROM catalog_financials WHERE ticker='UZAS'").fetchone()
        assert row['total_assets'] == 332548245.7
        assert row['total_liabilities'] == pytest.approx(184886318.3)
        assert row['net_income'] == 294295.9
        assert json.loads(row['balance_period'])['assets_start'] == 363687892.7
    finally:
        conn.close()
    assert balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=source / 'backup')['changed'] == 0


def test_manual_balance_override_is_not_silently_reverted(source):
    manual = correction('Confirmed by the reviewer against the signed report')
    result = balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=source / 'backup')
    assert result['plans'][0]['revert_correction_ids'] == []
    assert dq.approved_corrections_for('UZAS', 'NSBU', 2026, 2)['total_assets'] == 228022545.4


def test_real_alsm_unbalanced_filing_is_not_used_as_repair_evidence(source, monkeypatch):
    from tests.test_insurance_balance_consistency import FILINGS, workbook
    monkeypatch.setattr(sources, 'fetch_report_excel_data', lambda *_: {
        'ok': True, 'balance': workbook(FILINGS['ALSM_quarter_750'])})
    result = balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=source / 'backup')
    assert result['changed'] == 0
    assert result['skipped'][0]['reason'] == 'Filing balance does not reconcile'


@pytest.mark.parametrize('failure', ['unavailable', 'unbalanced', 'wrong_period'])
def test_unverified_sources_never_change_the_stored_data(source, monkeypatch, failure):
    bad = correction('Автоматическая подсказка по формуле: Assets = equity + liabilities.')
    if failure == 'unavailable':
        monkeypatch.setattr(sources, 'fetch_report_excel_data', lambda *_: {'ok': False})
    elif failure == 'unbalanced':
        from catalogue import parsing
        monkeypatch.setattr(parsing, 'compute_filing_values', lambda *_: {'source_values': {
            'total_assets': 100, 'total_equity': 50, 'total_liabilities': 60}})
    else:
        from catalogue import periods
        monkeypatch.setattr(periods, 'header_period_conflict', lambda *_: 'wrong period')
    result = balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=source / 'backup')
    assert result['changed'] == 0
    assert result['skipped']
    assert dq.approved_corrections_for('UZAS', 'NSBU', 2026, 2)['total_assets'] == 228022545.4
