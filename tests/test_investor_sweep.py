import pytest


# OpenInfo HMKB FY2025 consolidated PDF, printed page 40, Note 28.
NOTE = """JSCB Hamkorbank
Notes to the Consolidated Financial Statements – 31 December 2025
28 Earnings per Share
Basic earnings per share are calculated by dividing the profit or loss attributable to owners of the Group by
the weighted average number of ordinary shares in issue during the year, excluding treasury shares.
In millions of Uzbekistan Soums       2025       2024
Profit for the year attributable to the shareholders of the Bank       1,786,756       1,504,834
Less preference dividends declared       (5,051)       (6,061)
Profit for the year attributable to the ordinary shareholders of the Bank       1,781,705       1,498,773
Weighted average number of ordinary shares in issue (millions)       125,289       123,578
Basic and diluted earnings per ordinary share (expressed in
UZS per share)       14.22       12.13"""


@pytest.mark.parametrize('change', [None, ('14.22','142.2'), ('  2025       2024','  2024       2025'),
    ('UZS per share','USD per share'), ('(millions)','(thousands)'), ('ordinary shareholders','preferred shareholders')])
def test_hmkb_audited_eps_requires_matching_currency_class_dates_and_arithmetic(change):
    from financial_ingestion.investor_eps import reconciled_eps
    text = NOTE.replace(*change) if change else NOTE
    values = reconciled_eps(text, page=48)
    selected = [r for r in values if r['period_end']=='2025-12-31']
    if change:
        assert selected == []
    else:
        assert len(selected) == 1
        assert (selected[0]['raw_value'], selected[0]['scope'], selected[0]['page']) == ('14.22','consolidated',48)
        assert values[1]['raw_value'] == '12.13'


def test_coverage_includes_unresolved_issuers_historical_periods_and_sector_exclusions(monkeypatch):
    from financial_ingestion import investor_sweep
    def project(ticker, org):
        if ticker == 'BAD':
            raise ValueError('source unavailable')
        return [{'standard':'nsbu','scope':'separate','period':'2026Q3','status':'available',
                 'ratios':[{'metric_code':'eps_basic','value':None,'last_verified':{
                     'value':0,'period_end':'2025-12-31','verification_status':'verified'}},
                    {'metric_code':'price_to_book','value':None,'missing_inputs':['ordinary_shares']},
                    {'metric_code':'book_value_per_share','value':0,'verification_status':'verified'}]}]
    monkeypatch.setattr(investor_sweep, 'latest_reports', project)
    result = investor_sweep.coverage([{'ticker':'HMKB','org_id':'8'}, {'ticker':'BAD','org_id':'1'},
                                     {'ticker':'UNKNOWN','org_id':None}])
    bank, bad, unknown = result['issuers']
    m = bank['reports'][0]['metrics']
    assert m['eps_basic']['state']=='historical' and m['eps_basic']['period_end']=='2025-12-31'
    assert m['price_to_book']['missing_inputs']==['ordinary_shares']
    assert m['book_value_per_share']['state']=='verified' and m['ebit']['state']=='not_applicable'
    assert bad['error'] == 'source unavailable' and unknown['status']=='unresolved_issuer'
    assert result['issuer_count'] == 3


def test_approved_file_hash_binds_automatic_eps_and_caches_scan(monkeypatch, tmp_path):
    from financial_ingestion import investor_eps
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path/'catalog.db'))
    calls = []
    monkeypatch.setattr(investor_eps.documents, 'read_artifact', lambda sha: calls.append(sha) or b'pdf')
    monkeypatch.setattr(investor_eps, 'scan_pdf', lambda data, ocr: investor_eps.reconciled_eps(NOTE, page=48))
    for _ in range(2):
        investor_eps.archived_rows('approved-sha', ocr=True)
    snapshot = {'period_end':'2025-12-31','scope':'consolidated','payload':{
        'classification': {'period_start':'2025-01-01'}, 'source':{'file_hash':'approved-sha'}}}
    assert calls == ['approved-sha']
    assert investor_eps.published_rows(snapshot)[0]['raw_value'] == '14.22'
    assert not investor_eps.published_rows({**snapshot,'scope':'separate'})
    snapshot['payload']['source']['file_hash']='replaced-sha'
    assert not investor_eps.published_rows(snapshot)


def test_marketwide_inventory_lists_unlinked_ordinary_stocks_and_keeps_sibling_classes_together(monkeypatch, tmp_path):
    from catalogue.storage import get_catalog_conn
    from financial_ingestion import investor_sweep
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path/'market.db'))
    c = get_catalog_conn()
    with c:
        c.executemany("INSERT INTO catalog_companies(ticker,org_id,company_name) VALUES (?,?,'Hamkorbank')",
                      [('HMKB','8'),('HMKBP','8')])
    c.close()
    monkeypatch.setattr(investor_sweep, 'get_securities_map', lambda: {
        'HMKB':{'share_type':'ordinary'},'HMKBP':{'share_type':'preferred'},'AGMK':{'share_type':'ordinary'},
        'DMMT2B':{'share_type':'bond'}})
    assert investor_sweep.unlinked_equities() == [{'ticker':'AGMK','org_id':None}]


@pytest.mark.parametrize('override,eligible', [
    ({},True), ({'organization_name':'"Hamkorbank Leasing" AJ'},False),
    ({'organization_id':12},False), ({'status':'draft'},False),
    ({'published_at':'2027-05-07'},False), ({'report_form':'Audition'},False)])
def test_direct_openinfo_annual_eps_can_qualify_without_a_manual_issuer_record(override, eligible):
    from financial_ingestion import investor_eps
    url='https://openinfo.uz/media/msfo/ba173c49-969f-48b2-8657-64d386332c52.pdf'
    meta=dict(organization_id=8,organization_name='"Hamkorbank" ATB',status='approved',report_form='MSFO',
              period_type='annual',pdf_url=url,published_at='2026-05-07')
    row=investor_eps.reconciled_eps(NOTE,page=48)[0]
    result=investor_eps.official_filing({**meta, **override},url=url,org='8',row=row,
                                       end='2026-09-30',cutoff='2026-11-20')
    assert bool(result) is eligible
    if eligible:
        assert result['value']==14.22 and result['scope']=='consolidated' and result['page']==48
    assert not investor_eps.official_filing(meta,url=url,org='8',row={**row,'column':1},end='2026-09-30',cutoff='2026-11-20')


def test_latest_openinfo_approval_is_required_even_for_previously_verified_original(monkeypatch, tmp_path):
    from financial_ingestion import investor_eps, store
    monkeypatch.setenv('CATALOG_DB_PATH',str(tmp_path/'market.db'))
    url='https://openinfo.uz/media/msfo/ba173c49-969f-48b2-8657-64d386332c52.pdf'
    meta=dict(organization_id=8,organization_name='"Hamkorbank" ATB',status='approved',report_form='MSFO',
              period_type='annual',pdf_url=url,published_at='2026-05-07')
    monkeypatch.setattr(investor_eps.documents,'read_artifact',lambda sha:b'pdf')
    monkeypatch.setattr(investor_eps,'scan_pdf',lambda data,ocr:investor_eps.reconciled_eps(NOTE,page=48))
    investor_eps.archived_rows('sha',ocr=True)
    with store.transaction() as c:
        c.execute("INSERT INTO ingest_sources(id,org_id,ticker,url,category,metadata_json,first_seen,last_seen) "
                  "VALUES ('src','8','HMKB',?,'MSFO',?,'2026-05-07','2026-05-07')",(url,store.encoded(meta)))
        c.execute("INSERT INTO ingest_artifacts VALUES ('sha','example.pdf',1,'application/pdf','2026-05-07')")
        c.execute("INSERT INTO ingest_versions VALUES ('ver','src','sha',?,'2026-05-07')",(store.encoded(meta),))
        c.execute("UPDATE ingest_sources SET latest_version='ver' WHERE id='src'")
    read = lambda: investor_eps.official_eps('8','2026-09-30','2026-11-20','separate')
    assert read()['value']==14.22
    with store.transaction() as c:
        c.execute("UPDATE ingest_sources SET metadata_json=? WHERE id='src'",(store.encoded({**meta,'status':'withdrawn'}),))
    assert read() is None
