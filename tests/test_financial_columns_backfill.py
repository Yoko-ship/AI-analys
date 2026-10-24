import json
from pathlib import Path

from catalogue.storage import get_catalog_conn
from financial_columns import source_store


def test_existing_alkb_and_uztl_filings_populate_columns_without_rewriting_history(monkeypatch, tmp_path):
    from financial_columns import backfill
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    c = get_catalog_conn()
    with c:
        for ticker, issuer, name in [('ALKB','1','Aloqabank'), ('UZTL','2','O‘zbektelekom')]:
            c.execute('INSERT INTO catalog_companies(ticker,org_id,company_name) VALUES (?,?,?)', (ticker,issuer,name))
            for year in [2023,2024,2025]:
                c.execute("INSERT INTO catalog_reports(ticker,report_form,period_type,year,quarter,excel_url) VALUES (?,'NSBU','annual',?,0,?)",
                          (ticker,year,f'https://openinfo.uz/{ticker}/{year}.xlsx'))
    c.close()
    calls = []
    def fetch(ticker, form, year, quarter, **kw):
        assert kw == {'use_snapshot_cache': False}
        calls.append((ticker,year))
        data=json.loads(Path(f'tests/fixtures/openinfo/{ticker.lower()}_2025_complete_rows.json').read_text(encoding='utf-8'))
        return {'ok':True,'income':data,'balance':data}
    monkeypatch.setattr(backfill.catalogue_sources,'fetch_report_excel_data',fetch)
    result = backfill.run(annual_periods=2)
    assert result['imported'] == 4
    assert set(calls) == {('ALKB',2024),('ALKB',2025),('UZTL',2024),('UZTL',2025)}
    assert len(source_store.read('1',standard='NSBU',scope='separate')) == 2
    assert len(source_store.read('2',standard='NSBU',scope='separate')) == 2
    assert backfill.run(annual_periods=2)['imported'] == 0
    c=get_catalog_conn()
    assert c.execute('SELECT count(*) FROM catalog_financials').fetchone()[0] == 0
    c.close()


def test_failed_source_remains_retryable_without_stopping_other_issuers(monkeypatch, tmp_path):
    from financial_columns import backfill
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    candidates=[dict(ticker='ALKB',issuer_id='1',year=2025,quarter=0,template='bank',urls={}),
                dict(ticker='UZTL',issuer_id='2',year=2025,quarter=0,template='telecom',urls={})]
    monkeypatch.setattr(backfill,'pending',lambda annual_periods:candidates)
    def fetch(ticker,*args,**kwargs):
        if ticker=='ALKB': return {'ok':False,'error':'upstream unavailable'}
        data=json.loads(Path('tests/fixtures/openinfo/uztl_2025_complete_rows.json').read_text(encoding='utf-8'))
        return {'ok':True,'income':data,'balance':data}
    monkeypatch.setattr(backfill.catalogue_sources,'fetch_report_excel_data',fetch)
    result=backfill.run()
    assert result['imported']==1 and len(result['errors'])==1
    assert source_store.read('1',standard='NSBU',scope='separate')==[]
    assert source_store.read('2',standard='NSBU',scope='separate')[0]['rows']
