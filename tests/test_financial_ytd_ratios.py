"""Current-period ratios: HMKB's reported 9M 2026 case and basis guards."""
import csv
import io
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from financial_columns import ratios


@pytest.fixture
def hmkb_rows():
    # Captured source cells include the exact filing, row and original amount.
    payload=json.loads(Path('e2e/fixtures/hmkb-recent-reports.json').read_text())
    return [{'standard':payload['standard'],'scope':payload['scope'],
             'issuer_id':payload['issuer_id'],'unit':row.get('unit',payload['unit']),**cell}
            for row in payload['rows'] for cell in row['cells'].values()]


def calculate(rows, end='2026-09-30', basis='ytd', template='bank'):
    return {r['metric_id']:r for r in ratios.calculate(
        rows,ticker='HMKB',template=template,end=end,basis=basis)}


def test_hmkb_9m_current_ratios_use_year_opening_balances_and_reported_ytd(hmkb_rows):
    original=deepcopy(hmkb_rows)
    result=calculate(hmkb_rows)
    for metric,expected in {'roe':26.5133295211,'roa':4.9162481672,
                            'cir':1819867178/4249412165*100}.items():
        cell=result[metric]
        assert cell['quality']=='valid'
        assert float(cell['value'])==pytest.approx(expected)
        assert cell['period_start']=='2026-01-01'
        assert cell['period_end']=='2026-09-30'
        assert cell['basis']=='ytd'
        assert cell['annualized']==(metric!='cir')
        assert ('× 12 / 9' in cell['formula'])==(metric!='cir')
    assert [p['period_end'] for p in result['roe']['components']]==[
        '2026-09-30','2025-12-31','2026-09-30']
    assert result['roe']['components'][0]['raw_value']==1480422343
    assert 'report_id=1306' in result['roe']['components'][0]['source_url']
    # A published loan-loss charge is not a verified loan-only cost of risk;
    # total assets cannot stand in for the missing earning-assets base.
    assert result['nim']['value'] is None
    assert result['nim']['reason']=='AVERAGE_EARNING_ASSETS_MISSING'
    assert result['cost_of_risk']['value'] is None
    assert result['cost_of_risk']['reason']=='INPUTS_MISSING'
    assert hmkb_rows==original


@pytest.mark.parametrize('end,months',[('2026-03-31',3),('2026-06-30',6),('2026-09-30',9)])
def test_ytd_rate_annualization_depends_on_elapsed_months_only(hmkb_rows,end,months):
    # Synthetic period variants isolate the annualization policy.
    for row in hmkb_rows:
        if row['period_end']=='2026-09-30':
            row['period_end']=end
            if row['kind']=='stock':row['period_start']=end
    result=calculate(hmkb_rows,end=end)
    assert float(result['roe']['value'])==pytest.approx(
        1480422343/((6704709904+8185132247)/2)*100*12/months)
    assert f'× 12 / {months}' in result['roe']['formula']
    assert float(result['cir']['value'])==pytest.approx(1819867178/4249412165*100)
    assert not result['cir']['annualized']
    debt=result['liabilities_to_assets']
    assert float(debt['value'])==pytest.approx(36204146303/44389278550)
    assert not debt['annualized']
    assert debt['period_start']==end


@pytest.mark.parametrize('problem',['missing_opening','incompatible_scope','blocked_profit'])
def test_ytd_does_not_bypass_required_inputs_or_quality(hmkb_rows,problem):
    if problem=='missing_opening':
        hmkb_rows=[r for r in hmkb_rows if not (
            r['metric_id']=='total_equity' and r['period_end']=='2025-12-31')]
    else:
        profit=next(r for r in hmkb_rows if r['metric_id']=='net_income' and r['period_end']=='2026-09-30')
        profit.update({'scope':'consolidated'} if problem=='incompatible_scope' else {'quality':'blocked'})
    cell=calculate(hmkb_rows)['roe']
    assert cell['value'] is None
    assert cell['quality']==('missing' if problem=='missing_opening' else 'blocked')


def test_asof_stays_stock_only_and_quarter_cir_is_not_annualized(hmkb_rows):
    assert calculate(hmkb_rows,basis='as_of')['roe']['quality']=='not_applicable'
    # Explicit standalone flows, distinct from the captured YTD statements.
    for row in hmkb_rows:
        if row['period_end']=='2026-09-30' and row['kind']=='flow':
            row['period_start']='2026-07-01'
    cir=calculate(hmkb_rows,basis='quarter')['cir']
    assert float(cir['value'])==pytest.approx(1819867178/4249412165*100)
    assert cir['annualized'] is False


@pytest.mark.parametrize('freq',['annual','interim'])
def test_current_hmkb_ratios_reach_api_and_exports(hmkb_rows,monkeypatch,tmp_path,freq):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server.company.financial_routes import router
    from catalogue.storage import get_catalog_conn
    from financial_columns import service
    monkeypatch.setenv('CATALOG_DB_PATH',str(tmp_path/'catalog.db'))
    c=get_catalog_conn()
    with c:
        c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('HMKB','Hamkorbank','8')")
    c.close()
    monkeypatch.setattr(service.source_store,'read',lambda *a,**kw:[])
    monkeypatch.setattr(service.observations,'nsbu',lambda docs:deepcopy(hmkb_rows))
    app=FastAPI()
    app.include_router(router)
    query=f'view=template&freq={freq}'
    with TestClient(app) as client:
        response=client.get(f'/api/company/HMKB/financials/columns?{query}')
        exported=client.get(f'/api/company/HMKB/financials/columns.csv?{query}')
    assert response.status_code==exported.status_code==200
    payload=response.json()
    roe=next(r for r in payload['ratios'] if r['metric_id']=='roe')['cells']['2026-09-30']
    assert Decimal(roe['value']).quantize(Decimal('.01'))==Decimal('26.51')
    records=list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
    exported_roe=next(r for r in records if r['metric_id']=='roe' and r['period_end']=='2026-09-30')
    assert exported_roe['value']==roe['value']
    assert exported_roe['period_start']=='2026-01-01'
    assert '× 12 / 9' in exported_roe['formula']
