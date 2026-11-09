"""Real source discrepancies must not turn usable ratios into unexplained dashes."""
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from financial_columns import observations, ratios
from tests.test_financial_matrix import observation


REPORTS = json.loads(Path('tests/fixtures/financial_columns/reconciliation_reports.json').read_text())


def test_cbsk_screenshot_returns_reported_profit_with_reconciliation_warning():
    rows = observations.nsbu(REPORTS['CBSK']['documents'])
    issues = observations.check(rows)
    result = {r['metric_id']: r for r in ratios.calculate(
        rows, ticker='CBSK', template='general', end='2026-09-30', basis='ytd')}
    for metric, expected in [('roe', '24.12'), ('roa', '20.88')]:
        cell = result[metric]
        assert cell['quality'] == 'warn'
        assert Decimal(cell['value']).quantize(Decimal('.01')) == Decimal(expected)
        assert cell['reason'] == 'SOURCE_NET_PROFIT_MISMATCH'
        profit = cell['components'][0]
        assert profit['value'] == '33451374'  # Filed amount, never repaired by subtraction.
        assert profit['raw_value'] == [33451374, 0]
        assert 'report_id=18989' in profit['source_url']
        assert profit['reconciliation_issues'][0]['difference'] == '-31248'
    assert float(result['current_ratio']['value']) == pytest.approx(2.31984469794)
    assert float(result['asset_turnover']['value']) == pytest.approx(0.46403105264)
    current = next(i for i in issues if i['period_end'] == '2026-09-30')
    assert current['severity'] == 'warn'
    assert current['reported_total'] == '33451374'
    assert current['reconciled_total'] == '33420126'
    # The larger discrepancy in the next filing's comparative stays blocked.
    annual = next(r for r in rows if r['metric_id'] == 'net_income'
                  and r['period_end'] == '2024-12-31' and r['role'] == 'COMPARATIVE')
    assert annual['quality'] == 'blocked'


@pytest.mark.parametrize('ticker,metric,expected', [
    ('UZIR', 'total_equity', 'warn'),  # Nine thousand UZS in a large balance.
    ('KVTS', 'total_assets', 'blocked'),  # Assets versus an explicitly zero passive total.
])
def test_real_balance_discrepancies_keep_minor_and_material_errors_distinct(ticker, metric, expected):
    rows = observations.nsbu(REPORTS[ticker]['documents'])
    observations.check(rows)
    cell = next(r for r in rows if r['metric_id'] == metric and r['period_end'] == '2026-09-30'
                and r['role'] == 'PRIMARY')
    assert cell['quality'] == expected
    assert cell['reconciliation_issues']


@pytest.mark.parametrize('reported,reconciled,quality', [
    ('10000', '9999', 'valid'),  # Existing absolute rounding allowance.
    ('10010', '10000', 'warn'),  # Exactly 0.1% of the smaller total.
    ('10010.01', '10000', 'blocked'),
    ('10000', '10010', 'warn'),  # Direction of the discrepancy does not matter.
    ('-10010', '-10000', 'warn'),  # Losses have the same policy.
    ('0', '2', 'blocked'),
    ('2', '0', 'blocked'),
    ('2', '-2', 'blocked'),
])
def test_reconciliation_relative_boundary_never_hides_zero_or_sign_conflicts(reported, reconciled, quality):
    rows = [observation(k, v, '2026-09-30', 'flow') for k, v in [
        ('profit_before_tax', reconciled), ('income_tax', 0),
        ('other_profit_payments', 0), ('net_income', reported)]]
    original = deepcopy(rows)
    observations.check(rows)
    assert rows[-1]['quality'] == quality
    assert [r['value'] for r in rows] == [r['value'] for r in original]
    assert [r['raw_value'] for r in rows] == [r['raw_value'] for r in original]


def test_minor_later_check_cannot_downgrade_a_blocked_input():
    rows = [observation(k, v, '2026-09-30') for k, v in [
        ('total_assets', 100000), ('total_liabilities', 50000), ('total_equity', 10000),
        ('noncurrent_assets', 60000), ('current_assets', 40010),
        ('total_equity_liabilities', 100010)]]
    observations.check(rows)
    assert rows[0]['quality'] == 'blocked'
    assert rows[0]['reason'] == 'SOURCE_BALANCE_MISMATCH'
    assert {i['severity'] for i in rows[0]['reconciliation_issues']} == {'warn', 'blocked'}


def test_cbsk_warned_values_reach_public_api_and_export(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from catalogue.storage import get_catalog_conn
    from financial_columns import service
    from server.company.financial_routes import router
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    c = get_catalog_conn()
    with c:
        c.execute('INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES (?,?,?)',
                  ('CBSK', REPORTS['CBSK']['issuer_name'], REPORTS['CBSK']['issuer_id']))
    c.close()
    monkeypatch.setattr(service.source_store, 'read', lambda *a, **kw: deepcopy(REPORTS['CBSK']['documents']))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        payload = client.get('/api/company/CBSK/financials/columns?view=template').json()
        exported = client.get('/api/company/CBSK/financials/columns.csv?view=template&layout=table&tab=ratios&lang=en')
    roe = next(r for r in payload['ratios'] if r['metric_id'] == 'roe')['cells']['2026-09-30']
    assert roe['value'] is not None and roe['quality'] == 'warn'
    assert roe['reason'] == 'SOURCE_NET_PROFIT_MISMATCH'
    assert exported.status_code == 200
    assert roe['value'] in exported.text
