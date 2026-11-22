import json
from pathlib import Path

from catalogue.storage import get_catalog_conn
from financial_columns import source_store


def test_share_backfill_finds_older_quarters_in_attachment_index(monkeypatch, tmp_path):
    from collectors.openinfo import transport
    from financial_columns import backfill, share_disclosures
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'shares.db'))
    conn = get_catalog_conn()
    with conn:
        conn.execute("INSERT INTO catalog_companies(ticker,org_id,company_name) VALUES ('BIOK','396','Biokimyo')")
        for rid, year in [(18938,2026),(17697,2025)]:
            url = f'https://new-api.openinfo.uz/api/v2/reports/export-excel/?org_type=jsc&report_type=quarter&report_id={rid}'
            conn.execute("INSERT INTO catalog_reports(ticker,report_form,period_type,year,quarter,excel_url) "
                         "VALUES ('BIOK','NSBU','quarter',?,3,?)",(year,url))
    conn.close()
    pages = []
    def listing(session, path, params):
        assert path == '/reports/jsc/quarter/'
        pages.append(params['page'])
        rows = ([{'id':18938,'organization':396,'int_report':None},
                 {'id':17697,'organization':78,'int_report':'wrong.xlsx'}] if params['page'] == 1 else
                [{'id':17697,'organization':396,'int_report':'https://openinfo.uz/media/int_report/older.xlsx'}])
        return {'results':rows, 'total_pages':2}
    monkeypatch.setattr(transport,'_json_get',listing)
    imported = []
    def collect(session, **job):
        imported.append((job['ticker'],job['period_end']))
        return True
    monkeypatch.setattr(share_disclosures,'collect_form5',collect)
    assert backfill.collect_share_bases() == {'checked':1, 'imported':1, 'errors':[]}
    assert pages == [1,2]
    assert imported == [('BIOK','2025-09-30')]


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


def test_archive_recovery_matches_ordinary_issue_and_traded_date(monkeypatch, tmp_path):
    from catalogue import market_store
    from collectors.openinfo import transport
    from financial_columns import backfill
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'archive.db'))
    ticker, isin = 'ABKZ', 'UZ7047650005'
    response = {'ticker':'BIOK', 'results':[{'date':'2025-05-20','close':6100,'trading_volume':6}]}
    def archive(session, path, params):
        assert (path, params['isu_cd'], params['start_date']) == ('/iuzse/conclusions/', isin, '2025-03-31')
        return response
    monkeypatch.setattr(transport, '_json_get', archive)
    import pytest
    with pytest.raises(ValueError, match='ticker'):
        backfill.collect_valuation_quotes(None, ticker, isin, '2025-03-31')
    response['ticker'] = ticker
    assert backfill.collect_valuation_quotes(None, ticker, isin, '2025-03-31') == 1
    assert market_store.quote_at(isin, '2025-07-27')['close_price'] == 6100
    assert backfill.collect_valuation_quotes(None, ticker, isin, '2025-03-31') == 0


def test_warming_valuation_history_keeps_complete_filing_when_cache_is_partial(monkeypatch,tmp_path):
    from financial_columns import backfill
    monkeypatch.setenv('CATALOG_DB_PATH',str(tmp_path/'source.db'))
    full=json.loads(Path('tests/fixtures/openinfo/uztl_2025_complete_rows.json').read_text(encoding='utf-8'))
    job=dict(ticker='UZTL',issuer_id='2',year=2025,quarter=0,template='telecom',urls={'excel_url':full['source_url']})
    version=source_store.record_nsbu(**job,data={'ok':True,'income':full,'balance':full})
    partial={**full,'source_coverage':{'complete':False,'issues':['PARTIAL_SOURCE_IMPORT']}}
    monkeypatch.setattr(backfill.catalogue_sources,'fetch_report_excel_data',lambda *a,**kw:{'ok':True,'income':partial})
    backfill._import(job,cache_for_reports=True)
    assert source_store.read('2',standard='NSBU',scope='separate')[0]['source_version'] == version
