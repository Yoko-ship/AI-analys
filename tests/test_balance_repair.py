"""A real UZAS filing repairs source data without erasing reviewed decisions."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import data_quality as dq
from catalogue import balance_repair, financial_store, filings, sources, storage

FILING = json.loads((Path(__file__).parent / 'fixtures/sector_v22_filings.json').read_text(encoding='utf-8'))['UZAS']
BANK = json.loads((Path(__file__).parent / 'fixtures/ocbk_2025_balance.json').read_text(encoding='utf-8'))


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


def test_ocbk_derived_equity_cannot_validate_a_broken_filed_balance(source, monkeypatch):
    monkeypatch.setattr(filings, 'get_report_urls', lambda *_: {'excel_url': BANK['source_url']})
    monkeypatch.setattr(sources, 'fetch_report_excel_data', lambda *_: {'ok': True, 'balance': BANK})
    with pytest.raises(ValueError, match='Filing balance does not reconcile'):
        balance_repair.verified_balance('OCBK', 'NSBU', 2025, 0)


def test_unverified_repair_can_restore_only_its_own_unchanged_write(source, monkeypatch):
    bad = correction('Автоматическая подсказка по формуле: Assets = equity + liabilities.')
    assert balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=source/'backup')['changed'] == 1
    def unverified(**_):
        raise ValueError('Filing balance does not reconcile')
    monkeypatch.setattr(balance_repair, 'verified_balance', unverified)
    preview = balance_repair.rollback_unverified(backup_dir=source/'backup', apply=False)
    assert preview['restored'] == 0 and len(preview['plans']) == 1
    restored = balance_repair.rollback_unverified(backup_dir=source/'backup', apply=True)
    assert restored['restored'] == 1
    assert dq.approved_corrections_for('UZAS', 'NSBU', 2026, 2)['total_assets'] == 228022545.4
    conn = storage.get_catalog_conn()
    try:
        assert conn.execute("SELECT total_liabilities FROM catalog_financials WHERE ticker='UZAS'").fetchone()[0] == 80360618.0
    finally:
        conn.close()
    assert balance_repair.rollback_unverified(backup_dir=source/'backup', apply=True)['restored'] == 0


@pytest.mark.parametrize('ticker,org', [('HMKB', 'bank'), ('UZMK', 'jsc')])
def test_explicit_source_verification_accepts_real_balanced_other_sectors(source, monkeypatch, ticker, org):
    data = json.loads((Path(__file__).parent/'fixtures/sector_v22_filings.json').read_text(encoding='utf-8'))[ticker]['workbook']
    monkeypatch.setattr(filings, 'get_report_urls', lambda *_: {'excel_url': 'https://openinfo.uz/report?org_type=' + org})
    monkeypatch.setattr(sources, 'fetch_report_excel_data', lambda *_: {'ok': True, **data})
    verified = balance_repair.verified_balance(ticker, 'NSBU', 2026, 2)
    assert verified['total_assets'] == pytest.approx(verified['total_equity'] + verified['total_liabilities'], rel=.0005)


@pytest.mark.parametrize('change', ['new_balance', 'manual_review', 'source_unavailable'])
def test_rollback_does_not_undo_later_changes_or_react_to_source_outages(source, monkeypatch, change):
    bad = correction('Автоматическая подсказка по формуле: Assets = equity + liabilities.')
    balance_repair.repair(tickers=['UZAS'], apply=True, backup_dir=source/'backup')
    def unverified(**_):
        raise ValueError('Balance workbook unavailable' if change == 'source_unavailable' else 'Filing balance does not reconcile')
    monkeypatch.setattr(balance_repair, 'verified_balance', unverified)
    conn = storage.get_catalog_conn()
    try:
        with conn:
            if change == 'new_balance':
                conn.execute("UPDATE catalog_financials SET total_assets=500000000 WHERE ticker='UZAS'")
            elif change == 'manual_review':
                conn.execute("UPDATE data_corrections SET reviewed_by='later-human-review' WHERE id=?", (bad['id'],))
    finally:
        conn.close()
    assert balance_repair.rollback_unverified(backup_dir=source/'backup', apply=True)['restored'] == 0
