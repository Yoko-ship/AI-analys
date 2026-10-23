"""Real insurer filings must survive import without losing their reserve section."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest

import data_quality as dq
import openinfo_reconcile as reconcile
import fundamentals
import public_contract
from catalogue import financial_store, parsing, storage, snapshots
from financial_analysis.sector_report import make_report
from sector_report_service import map_special_lines


FILINGS = json.loads((Path(__file__).parent / 'fixtures/insurance_balance_filings.json').read_text(encoding='utf-8'))


def workbook(detail):
    rows = reconcile._rows(detail, 'quarter_balance_sheet_report', 'balance_sheet_report')
    return {'sheets': [{'table_rows': [
        {'label': r['title'], 'source_cells': [r['tnum'], r['value1'], r['value2']]}
        for r in rows
    ]}]}


@pytest.mark.parametrize('name', FILINGS)
def test_json_import_and_workbook_agree_on_all_insurance_liabilities(name):
    detail = FILINGS[name]
    imported = reconcile.extract_metrics(detail)
    parsed = parsing.extract_insurance_balance(workbook(detail))
    assert imported['total_liabilities'] == pytest.approx(parsed['total_liabilities'])
    assert imported['balance']['assets_end'] == parsed['total_assets']
    assert imported['balance']['equity_end'] == parsed['total_equity']


@pytest.mark.parametrize('zero_reserves', [False, True])
def test_missing_reserve_section_is_not_treated_as_zero(zero_reserves):
    detail = deepcopy(FILINGS['UZAS_quarter_765'])
    rows = detail['quarter_balance_sheet_report']
    for row in rows:
        if row['tnum'] in ('580', '670', '720'):
            row['value2'] = '0' if zero_reserves else None
    imported = reconcile.extract_metrics(detail)
    if zero_reserves:
        assert imported['total_liabilities'] == 80_360_618.0
    else:
        assert imported['total_liabilities'] is None


@pytest.mark.parametrize('assets', [332_548_245.7, None])
def test_uzas_balance_suggestion_cannot_auto_approve_the_wrong_asset_total(monkeypatch, tmp_path, assets):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    financial_store.upsert_financials_cache('UZAS', 'NSBU', 2026, 2, {
        'revenue': 111_891_908.5, 'net_income': 294_295.9,
        'total_assets': assets, 'total_equity': 147_661_927.4,
        # The production JSON parser omitted the separate reserve section.
        'total_liabilities': 80_360_618.0,
    })
    monkeypatch.setattr(dq, '_official_report_evidence', lambda *_: {
        'source_url': FILINGS['UZAS_quarter_765']['source_url'],
        'source_reference': 'UZAS NSBU 2026 Q2, balance lines 490, 570, 720, 1190',
        'available': True,
    })
    dq.scan_financial_issues()
    issue = next(i for i in dq.list_issues()['items'] if
                 i['rule_code'] == 'BALANCE_MISMATCH' or i['field'] == 'total_assets')
    proposal = dq.suggest_correction(issue['id'])
    assert proposal['recommended']['field'] == 'total_assets'
    assert proposal['recommended']['value_thousands_uzs'] == 228_022_545.4
    # Attaching the filing's URL does not verify the proposed number against it.
    with pytest.raises(dq.DataQualityError, match='official filing'):
        dq.auto_apply_issue(issue['id'], 'reviewer@example.test')
    assert dq.list_corrections(ticker='UZAS')['items'] == []
    conn = storage.get_catalog_conn()
    try:
        row = conn.execute("SELECT total_assets FROM catalog_financials WHERE ticker='UZAS'").fetchone()
        assert row['total_assets'] == assets
    finally:
        conn.close()


def test_uzas_import_storage_quality_scan_and_both_public_returns_agree(monkeypatch, tmp_path):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    metrics = reconcile.extract_metrics(FILINGS['UZAS_quarter_765'])
    metrics['net_income'] = 294_295.9  # Filed Form 2, 2026 H1, thousands of UZS.
    row = reconcile.admin_push_row(reconcile._figures('UZAS', metrics, {'year': 2026, 'quarter': 2}))
    financial_store.bulk_upsert_financials([row])
    dq.scan_financial_issues()
    assert not [i for i in dq.list_issues()['items'] if i['rule_code'] == 'BALANCE_MISMATCH']
    fin = snapshots.get_all_financials()['UZAS']
    assert fin['balance']['net_insurance_reserves'] == pytest.approx(104_525_700.3)
    result = fundamentals.issuer_multiples([], fin, {}, today=date(2026, 10, 21))
    market = public_contract.multiplier_contract(result, [], fin, {})

    filing = json.loads((Path(__file__).parent / 'fixtures/sector_v22_filings.json').read_text(encoding='utf-8'))['UZAS']
    snapshot = {'organization_type': 'insurance', 'standard': 'nsbu', 'scope': 'separate',
                'period': '2026Q2', 'period_basis': 'cumulative_ytd', 'source': filing['source'],
                'current_values': {}, 'previous_values': {}, 'opening_values': {}, 'quality': {'data_quality': []}}
    map_special_lines(snapshot, filing['workbook'], 'insurance')
    report = make_report(snapshot, filing['issuer'], today=date(2026, 10, 21), workbook=filing['workbook'])
    analysis = {r['metric_code']: r for r in report['ratios']}
    for code, expected in [('roe', 0.398936377693087), ('roa', 0.16907820997416934)]:
        assert market[code]['value'] == pytest.approx(expected, rel=1e-10)
        assert analysis[code]['value'] == pytest.approx(expected, rel=1e-10)


def test_insurer_short_term_investments_preserve_filed_current_and_opening():
    filing=json.loads((Path(__file__).parent/'fixtures/sector_v22_filings.json').read_text())['UZAS']
    snapshot={'current_values':{},'previous_values':{},'opening_values':{}}
    map_special_lines(snapshot,filing['workbook'],'insurance')
    assert float(snapshot['current_values']['short_term_investments'])==56_790_000
    assert float(snapshot['opening_values']['short_term_investments'])==59_478_954.1
    assert snapshot['field_sources']['short_term_investments']['source_line_id']=='insurance:balance:c460'


@pytest.mark.parametrize('closing,expected',[(69_033_187.4,-69_033_187.4),(0,0),(None,None)])
def test_insurer_expense_line_090_does_not_block_history_refresh(closing,expected):
    filing=json.loads((Path(__file__).parent/'fixtures/sector_v22_filings.json').read_text())['UZAS']
    income=deepcopy(filing['workbook']['income'])
    for sheet in income['sheets']:
        for row in sheet.get('table_rows',[]):
            if str(row.get('label','')).startswith('Расходы периода, всего'):
                row['source_cells'][-1]=closing
                if closing is None:row['source_cells'][-2]=None
    values=parsing.compute_filing_values(income,filing['workbook']['balance'])['source_values']
    assert values['operating_expenses']==expected
