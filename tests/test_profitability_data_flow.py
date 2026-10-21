"""Same-period source facts and reviewed corrections survive every adapter."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest

import fundamentals
from catalogue import financial_store, parsing, ratios, snapshots
from sector_report_service import map_special_lines

FILINGS = json.loads((Path(__file__).parent / 'fixtures/sector_v22_filings.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('ticker', ['UZMK', 'UZAS'])
def test_workbook_refresh_preserves_opening_balance_and_return(ticker, monkeypatch, tmp_path):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    wb = FILINGS[ticker]['workbook']
    values = parsing.compute_filing_values(wb['income'], wb['balance'])['source_values']
    financial_store.upsert_financials_cache(ticker, 'NSBU', 2026, 2, values)
    stored = snapshots.get_all_financials()[ticker]
    assert stored['balance'] == values['balance']
    original = {'year': 2026, 'quarter': 2, **values}
    for code in ('roe', 'roa'):
        expected = fundamentals.issuer_multiples([], original, {}, today=date(2026, 10, 21))[code]['value']
        assert fundamentals.issuer_multiples([], stored, {}, today=date(2026, 10, 21))[code]['value'] == expected


def test_current_stored_totals_replace_stale_nested_closing_values():
    old = {'assets_start': 363_687_892.7, 'assets_end': 228_022_545.4,
           'equity_start': 147_418_608.2, 'equity_end': 147_661_927.4}
    assert ratios._cached_balance(old, 332_548_245.7, 0)['assets_end'] == 332_548_245.7
    assert ratios._cached_balance(old, 332_548_245.7, 0)['equity_end'] == 0


@pytest.mark.parametrize('ticker,org', [('UZAS', 'insurance'), ('HMKB', 'bank')])
def test_special_form_enrichment_keeps_reviewed_current_values(ticker, org):
    corrected = {'net_income': 0, 'total_assets': 500_000_000,
                 'total_equity': 100_000_000, 'total_liabilities': 400_000_000}
    snapshot = {'current_values': dict(corrected), 'previous_values': {}, 'opening_values': {},
                'reviewed_correction_fields': list(corrected), 'quality': {'data_quality': []}}
    map_special_lines(snapshot, deepcopy(FILINGS[ticker]['workbook']), org)
    for field, expected in corrected.items():
        assert float(snapshot['current_values'][field]) == expected


@pytest.mark.parametrize('missing_codes', [('580', '670'), ('580', '670', '720'), ('1190',)])
def test_insurance_analysis_and_parser_agree_when_reserve_cells_are_missing(missing_codes):
    wb = deepcopy(FILINGS['UZAS']['workbook'])
    # Remove complete source lines so no alternate representation can restore them.
    for sheet in wb['balance']['sheets']:
        sheet['table_rows'] = [r for r in sheet['table_rows']
                               if (r.get('numeric_values') or [None])[0] not in {int(c) for c in missing_codes}]
    expected = parsing.extract_insurance_balance(wb['balance'])['total_liabilities']
    snapshot = {'current_values': {}, 'previous_values': {}, 'opening_values': {}, 'quality': {'data_quality': []}}
    map_special_lines(snapshot, wb, 'insurance')
    actual = snapshot['current_values']['total_liabilities']
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected)


def test_annual_snapshot_uses_the_stored_annual_correction_key(monkeypatch):
    import issuer_financials as issuer
    import data_quality
    values = {'revenue': 100, 'net_income': 0, 'total_assets': 332_548_245.7,
              'total_equity': 147_661_927.4, 'total_liabilities': 184_886_318.3}
    monkeypatch.setattr(issuer, 'get_financials_series', lambda *_: {'2025': values})
    monkeypatch.setattr(issuer, 'report_rows', lambda *_: [])
    monkeypatch.setattr(data_quality, 'approved_corrections_for',
                        lambda ticker, form, year, quarter: {'net_income': 0} if quarter == 0 else {})
    company = {'id': 'UZAS', 'ticker': 'UZAS', 'name': 'Uzagrosugurta', 'sector': 'insurance', 'isin': 'test'}
    snapshot = issuer.financial_snapshot(company, 'nsbu', '2025', 'separate')
    assert snapshot['reviewed_correction_fields'] == ['net_income']
