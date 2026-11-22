import json
from pathlib import Path

from catalogue.storage import get_catalog_conn
from financial_columns import source_store


def test_hmkb_sibling_filing_reaches_ordinary_ticker_without_existing_share_basis(monkeypatch, tmp_path):
    from financial_columns import backfill, share_disclosures
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path/'test.db'))
    conn = get_catalog_conn()
    with conn:
        for ticker in ('HMKB','HMKBP'):
            conn.execute('INSERT INTO catalog_companies(ticker,org_id,company_name) VALUES (?,\'8\',\'Hamkorbank\')',(ticker,))
        for quarter, rid in [(2,1201),(3,1306)]:
            url = f'https://new-api.openinfo.uz/api/v2/reports/export-excel/?org_type=bank&report_type=quarter&report_id={rid}'
            conn.execute("INSERT INTO catalog_reports(ticker,report_form,period_type,year,quarter,excel_url) "
                         "VALUES ('HMKBP','NSBU','quarter',2026,?,?)",(quarter,url))
    conn.close()
    monkeypatch.setattr(share_disclosures, 'filing_keys', lambda: set())
    warmed = []
    monkeypatch.setattr(backfill, '_import', lambda job, **kw: warmed.append((job['ticker'],job['quarter'])))
    assert backfill.collect_valuation_history(issuer_ids={'8'})['filings'] == 1
    assert warmed == [('HMKB',3)]


def test_financial_bond_only_issuer_does_not_require_a_share_valuation_workbook(monkeypatch, tmp_path):
    from financial_columns import backfill, share_disclosures
    monkeypatch.setenv('CATALOG_DB_PATH',str(tmp_path/'test.db'))
    jobs=[dict(issuer_id='1058',ticker='ACMT1B2',template='microfinance',year=2026,quarter=3),
          dict(issuer_id='8',ticker='HMKB',template='bank',year=2026,quarter=3)]
    monkeypatch.setattr(backfill,'_recent_jobs',lambda _:jobs)
    import securities_catalog
    monkeypatch.setattr(securities_catalog,'get_securities_map',lambda:{
        'ACMT1B2':{'share_type':'bond'},'HMKB':{'share_type':'ordinary'}})
    monkeypatch.setattr(share_disclosures,'filing_keys',lambda:set())
    warmed=[]
    monkeypatch.setattr(backfill,'_import',lambda j,**kw:warmed.append(j['ticker']))
    assert backfill.collect_valuation_history()['filings']==1
    assert warmed==['HMKB']


def test_nightly_share_discovery_checks_bank_attachments_and_respects_issuer_subset(monkeypatch):
    from collectors.openinfo import transport
    from financial_columns import backfill, share_disclosures
    jobs = [dict(ticker=ticker, issuer_id=org, template=kind, year=2026, quarter=3,
                 urls={'excel_url': f'https://new-api.openinfo.uz/api/v2/reports/export-excel/?org_type={kind}&report_type=quarter&report_id={rid}'})
            for ticker, org, kind, rid in [('HMKB','8','bank',1306), ('BIOK','396','jsc',18938)]]
    monkeypatch.setattr(backfill, '_recent_jobs', lambda _: jobs)
    paths = []
    def listing(session, path, params):
        paths.append(path)
        return {'total_pages': 1, 'results': [{'id':1306, 'organization':8, 'int_report':'test.xlsx'}]}
    monkeypatch.setattr(transport, '_json_get', listing)
    collected = []
    monkeypatch.setattr(share_disclosures, 'collect_form5', lambda session, **job: collected.append(job['ticker']) or False)
    assert backfill.collect_share_bases(issuer_ids={'8'})['checked'] == 1
    assert paths == ['/reports/bank/quarter/'] and collected == ['HMKB']


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
