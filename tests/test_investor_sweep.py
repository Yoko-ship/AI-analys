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


@pytest.mark.parametrize('change', [None, ('(1,476)', '(1,475)'), ('2,787,191', '278,719'),
                                    ('millions of Uzbek Soums', 'thousands of Uzbek Soums')])
def test_aloqabank_eps_after_preference_allocation(change):
    from financial_ingestion import investor_eps
    text = """JOINT STOCK COMMERCIAL “ALOQABANK” AND ITS SUBSIDIARIES
NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS - 31 DECEMBER 2025
(In millions of Uzbek Soums, unless otherwise indicated)
28. EARNINGS PER SHARE
Basic earnings per share are calculated by dividing the profit or loss attributable to owners of the Bank by the weighted
average number of ordinary shares in issue during the year, excluding treasury shares. The Bank has no dilutive potential
ordinary shares; therefore, the diluted earnings per share equal the basic earnings per share. Earnings per share are
calculated as follows:
2025 2024
Profit /(loss) for the year attributable to the ordinary shareholders of the Bank (194,251) 252,306
Less undistributed profit or loss for the year attributable to preference
shareholders based on terms of the shares (1,476) (7,380)
Profit/(loss) for the year attributable to the ordinary shareholders of the
Bank

(195,727) 244,926
Weighted average number of ordinary shares in issue (millions) 2,787,191 2,054,004
Total basic and diluted earnings per share attributable to the owners of
the bank (expressed in UZS per share)

(0.07) 0.12"""
    rows = investor_eps.reconciled_eps(text.replace(*change) if change else text, page=58)
    if change:
        assert rows == []
        return
    assert [r['raw_value'] for r in rows] == ['-0.07','0.12']
    url = 'https://openinfo.uz/media/msfo/b11dc39a-8ced-4bf9-9c1a-f29f451ebc43.pdf'
    meta = dict(organization_id=10, organization_name='AT "Aloqabank"', status='approved',
                report_form='MSFO', period_type='annual', pdf_url=url, published_at='2026-06-11')
    def official(name):
        return investor_eps.official_filing({**meta, 'organization_name':name}, url=url, org='10',
                                           row=rows[0], end='2026-09-30', cutoff='2026-11-20')
    assert official(meta['organization_name'])['value'] == -0.07
    assert official('AT "Aloqabank Leasing"') is None


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


# The native text layer of ALSM’s FY2021 audited income statement, PDF page 5.
ALSM_STATEMENT = """Акционерное Общество СК «ALSKOM» и ее дочернее предприятие
Консолидированный отчет о прибылях и убытках и прочем совокупном доходе
(в тысячах узбекских сумов)
Статьи Примечание 31 декабря
2021 года
31 декабря
2020 года
ЧИСТАЯ ПРИБЫЛЬ 3 378 112 9 334 611
Базовая прибыль на акцию (в сумах) 34 194,45 687,14"""


@pytest.mark.parametrize('change', [None, ('2021 года', '2019 года'), ('в сумах', 'в тысячах сумов'),
    ('Базовая прибыль', 'Разводненная прибыль'), ('Примечание ', ''), ('194,45', '—'),
    ('194,45', '194 45'), ('ALSKOM', 'ALSKOM Leasing')])
def test_alsm_disclosed_eps_keeps_filing_year_class_currency_and_identity(change):
    from financial_ingestion import investor_eps
    url = 'https://openinfo.uz/media/msfo/audit_MSFO_2021_07_07_2021.pdf'
    meta = dict(organization_id=683, organization_name='"Alskom sug\'urta kompaniyasi" AJ',
                status='approved', report_form='MSFO', period_type='annual', pdf_url=url, published_at='2023-06-14')
    text = ALSM_STATEMENT.replace(*change) if change else ALSM_STATEMENT
    facts = [investor_eps.official_filing(meta, url=url, org='683', row=row, end='2026-09-30', cutoff='2026-11-20')
             for row in investor_eps.statement_eps(text, page=5, printed_note=lambda label: '34')]
    assert [fact for fact in facts if fact] == ([] if change else [
        dict(standard='ifrs', scope='consolidated', period='2021', value=194.45, unit='UZS_per_share', source_url=url, page=5)])


def test_missing_note_column_cannot_turn_part_of_a_grouped_eps_into_a_note_number():
    from financial_ingestion import investor_eps
    # The same flattened row could say 34 194,45 in a single amount cell.
    assert investor_eps.statement_eps(ALSM_STATEMENT, page=5, printed_note=lambda label: '') == []


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


def test_coverage_counts_hmkb_linked_annual_eps_with_its_own_period_and_scope():
    from financial_ingestion.investor_sweep import _metric
    filing = {'standard':'ifrs','scope':'consolidated','period':'2025','value':14.22,
              'unit':'UZS_per_share','source_url':'https://openinfo.uz/media/msfo/ba173c49-969f-48b2-8657-64d386332c52.pdf','page':48}
    report = {'status':'available','ratios':[{'metric_code':'eps_basic','value':None,'other_filing':filing}]}
    metric = _metric('eps_basic', report)
    assert metric['state'] == 'other_filing' and metric['other_filing'] == filing


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


def test_pdf_eps_scan_leaves_uznf_workbook_to_the_workbook_importer(monkeypatch,tmp_path):
    from financial_ingestion import documents,investor_sweep,store,workbooks
    monkeypatch.setenv('CATALOG_DB_PATH',str(tmp_path/'catalog.db'))
    url='https://openinfo.uz/media/msfo/33ce9408-a087-4411-83d8-f310d423fa47.xlsx'
    sha='46a4720131109eedf9a6102d831090768ca7cd2544209c5168b9f64436c98ac6'
    with store.transaction() as c:
        source=documents.register(c,org_id='1059',ticker='UZNF',url=url,category='MSFO',metadata={},processor='test')
        c.execute('INSERT INTO ingest_artifacts VALUES (?,?,?,?,?)',(sha,'original.xlsx',41237,workbooks.MEDIA_TYPE,'2026-11-27'))
        c.execute('INSERT INTO ingest_versions VALUES (?,?,?,?,?)',('xlsx-version',source,sha,'{}','2026-11-27'))
        c.execute('UPDATE ingest_sources SET latest_version=? WHERE id=?',('xlsx-version',source))
        pdf=documents.register(c,org_id='1059',ticker='UZNF',url='https://openinfo.uz/media/msfo/uznf-annual.pdf',
                               category='MSFO',metadata={'period_type':'annual','published_at':'2026-05-01'},processor='test')
    latest,history=investor_sweep._filing_rounds({'1059'})
    assert [r[2] for r in latest+history]==[pdf]
    with store.connect() as c:
        assert c.execute('SELECT latest_version FROM ingest_sources WHERE id=?',(source,)).fetchone()['latest_version']=='xlsx-version'


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


def test_alsm_catalog_archive_can_regain_approval_only_after_checking_the_original(monkeypatch, tmp_path):
    from financial_ingestion import documents, investor_eps, store

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('FINANCIAL_ARTIFACT_DIR', str(tmp_path / 'files'))
    url = 'https://openinfo.uz/media/msfo/audit_MSFO_2021_07_07_2021.pdf'
    thin = dict(org_id='683', report_form='MSFO', period_type='annual', pdf_url=url,
                published_at='2023-06-14', openinfo_report_id='2542')
    full = dict(id=2542, organization_id=683, organization_name='"Alskom sug\'urta kompaniyasi" AJ',
                report_form='MSFO', period_type='annual', pdf_url=url, status='approved', published_at='2023-06-14')
    payload = b'%PDF-ALSM historical filing'
    with store.transaction() as conn:
        source = documents.register(conn, org_id='683', ticker='ALSM', url=url, category='MSFO',
                                    processor='test', metadata=thin)
    first = documents.fetch_job(store.claim(stages=('FETCH',), source_id=source), 'test', fetch=lambda url: payload)
    sha, _ = documents.archive(payload)
    rows = investor_eps.statement_eps(ALSM_STATEMENT, page=5, printed_note=lambda _: '34')
    monkeypatch.setattr(investor_eps, 'scan_pdf', lambda *args, **kwargs: rows)
    investor_eps.archived_statements(sha)
    read = lambda: investor_eps.official_eps('683', '2026-09-30', '2026-11-20', 'separate')
    assert read() is None
    def register(meta):
        with store.transaction() as conn:
            documents.register(conn, org_id='683', ticker='ALSM', url=url, category='MSFO', processor='test',
                               metadata=meta, refresh_days=0)
    register(full)
    assert read() is None
    second = documents.fetch_job(store.claim(stages=('FETCH',), source_id=source), 'test', fetch=lambda url: payload)
    assert second == first and read()['value'] == 194.45
    register(thin)
    assert read()['value'] == 194.45
    register({**full, 'status':'withdrawn'})
    assert read() is None


def test_market_collection_rechecks_an_older_alsm_original_against_the_issuer_listing(monkeypatch, tmp_path):
    import ifrs_financials
    from catalogue import sources
    from financial_ingestion import documents, investor_eps, investor_sweep, store

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('FINANCIAL_ARTIFACT_DIR', str(tmp_path / 'files'))
    url = 'https://openinfo.uz/media/msfo/audit_MSFO_2021_07_07_2021.pdf'
    org, ticker, name = '683', 'ALSM', '"Alskom sug\'urta kompaniyasi" AJ'
    meta = dict(org_id=org, report_form='MSFO', period_type='annual', pdf_url=url,
                published_at='2023-06-14', openinfo_report_id='2542')
    official = dict(id=2542, organization=683, organization_name=name, pdf_url=url, status='approved',
                    report_type='MSFO', properties={'report_type':'annual'}, pub_date='2023-06-14')
    with store.transaction() as conn:
        conn.execute('INSERT INTO catalog_companies(ticker,org_id,company_name) VALUES (?,?,?)',(ticker,org,name))
        source = documents.register(conn, org_id=org, ticker=ticker, url=url, category='MSFO', processor='test', metadata=meta)
    downloads = []
    monkeypatch.setattr(ifrs_financials, 'download_pdf', lambda url, **kwargs: downloads.append(url) or b'%PDF-original')
    investor_sweep._fetch_filing(source)
    monkeypatch.setattr(sources, '_fetch_main_results', lambda session, issuer, org_id: ([official], None))
    monkeypatch.setattr(investor_eps, 'scan_pdf', lambda *a, **kw:
                        investor_eps.statement_eps(ALSM_STATEMENT, page=5, printed_note=lambda _: '34'))
    monkeypatch.setattr(investor_eps, 'archived_rows', lambda *a, **kw: [])
    monkeypatch.setattr(investor_sweep.backfill, '_recent_jobs', lambda _: [])
    for _ in range(2):
        result = investor_sweep.collect([{'ticker':ticker, 'org_id':org}], ocr=False)
        assert not result['errors']
        assert investor_eps.official_eps(org, '2026-09-30', '2026-11-20', 'separate')['value'] == 194.45
    assert downloads == [url, url]


def test_market_scan_visits_latest_filing_for_every_issuer_before_history(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import hashlib
    import ifrs_financials
    from financial_ingestion import documents, investor_sweep, store

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'market.db'))
    monkeypatch.setenv('FINANCIAL_ARTIFACT_DIR', str(tmp_path / 'pdfs'))
    official = 'https://openinfo.uz/media/msfo/'
    hmkb_latest = 'ba173c49-969f-48b2-8657-64d386332c52.pdf'
    filings = [
        ('8', 'HMKB', 'audit_report_2022_RUS.pdf', '2023-05-22'),
        ('8', 'HMKB', 'eb302c3c-5999-4f8a-bae5-986932590249.pdf', '2025-04-14'),
        ('19', 'AGBA', 'agba-prior.pdf', '2020-04-01'),
        ('19', 'AGBA', 'agba-latest.pdf', '2021-04-01'),
        ('8', 'HMKB', hmkb_latest, '2026-05-07'),
        ('396', 'BIOK', 'biok-latest.pdf', '2025-06-01'),
    ]
    def content(name):
        return b'%PDF-' + name.encode()
    with store.transaction() as conn:
        for org, ticker, name, filed in filings:
            meta = {'period_type':'annual', 'published_at':filed, 'status':'approved'}
            source = documents.register(conn, org_id=org, ticker=ticker, url=official+name,
                                        category='MSFO', metadata=meta, processor='test')
            if name == hmkb_latest:  # New in the issuer listing, not yet archived by the document worker.
                continue
            sha, path = documents.archive(content(name))
            conn.execute('INSERT INTO ingest_artifacts VALUES (?,?,?,?,?)', (sha,path,1,'application/pdf',filed))
            conn.execute('INSERT INTO ingest_versions VALUES (?,?,?,?,?)', (sha,source,sha,store.encoded(meta),filed))
            conn.execute('UPDATE ingest_sources SET latest_version=? WHERE id=?', (sha,source))

    downloaded = []
    def download(url, **_):
        downloaded.append(url)
        return content(url.rsplit('/',1)[-1])
    monkeypatch.setattr(ifrs_financials, 'download_pdf', download)
    monkeypatch.setattr(investor_sweep.backfill, '_recent_jobs', lambda _: [])
    names = {hashlib.sha256(content(f[2])).hexdigest():f[2] for f in filings}
    scanned = []
    statements = []
    monkeypatch.setattr(investor_sweep.investor_eps, 'archived_statements',
                        lambda sha: statements.append((names[sha], len(scanned))) or [], raising=False)
    def scan(sha, *, ocr):
        scanned.append(names[sha])
        return []
    monkeypatch.setattr(investor_sweep.investor_eps, 'archived_rows', scan)
    # A single latest filing can take longer than the entire historical OCR allowance.
    monkeypatch.setattr(investor_sweep, 'time', SimpleNamespace(monotonic=lambda: len(scanned)*1900))
    companies = [{'org_id':o, 'ticker':t} for o,t in [('8','HMKB'),('19','AGBA'),('396','BIOK')]]
    results = investor_sweep.collect(companies, ocr=True)
    assert set(scanned[:3]) == {hmkb_latest, 'agba-latest.pdf', 'biok-latest.pdf'}
    # Every searchable older statement gets checked before a slow historical OCR job.
    assert {name for name, count in statements if count == 3} >= {
        'audit_report_2022_RUS.pdf', 'eb302c3c-5999-4f8a-bae5-986932590249.pdf', 'agba-prior.pdf'}
    assert len(scanned) == 4 and scanned[3] == 'eb302c3c-5999-4f8a-bae5-986932590249.pdf'
    assert downloaded == [official+hmkb_latest]
    assert results['pdfs_pending'] == 2 and not results['errors']


def test_statutory_and_ifrs_latest_passes_both_precede_historical_work(monkeypatch):
    from financial_ingestion import investor_sweep as sweep
    calls = []
    def valuations(**kwargs):
        phase = kwargs.get('historical')
        calls.append('history balances' if phase else 'latest balances')
        return {'filings':1,'quotes':0,'errors':[]}
    monkeypatch.setattr(sweep, '_filing_rounds', lambda ids: (
        [('2026','8','a','new')], [('2025','8','b','old')]))
    monkeypatch.setattr(sweep.investor_eps,'archived_rows',lambda sha, **kw: calls.append(sha) or [])
    monkeypatch.setattr(sweep.investor_eps, 'archived_statements', lambda sha: [])
    monkeypatch.setattr(sweep.backfill, 'collect_valuation_history', valuations)
    monkeypatch.setattr(sweep.backfill, '_recent_jobs', lambda _: [])
    result = sweep.collect([{'org_id':'8','ticker':'HMKB'}], ocr=True)
    assert max(calls.index('new'), calls.index('latest balances')) < min(calls.index('old'), calls.index('history balances'))
    assert result['valuation_history']['filings'] == 2


def test_reported_eps_backfill_checks_fresh_listings_before_both_rounds(monkeypatch):
    from catalogue import snapshots, sources
    from financial_ingestion import bulk, investor_sweep

    events = []
    issuers = [{'ticker':'ALSM','org_id':'683','company_name':'Alskom'}, {'ticker':'HMKB','org_id':'8','company_name':'Hamkorbank'}]
    monkeypatch.setattr(bulk, 'issuers', lambda: (issuers, []))
    monkeypatch.setattr(sources, '_fetch_main_results', lambda session, name, org: ([{'organization':org}], None))
    monkeypatch.setattr(snapshots, '_remember_ifrs_sources', lambda **kw: events.append(kw['ticker']))
    monkeypatch.setattr(investor_sweep, '_filing_rounds', lambda ids: ([('recent','8','new','sha1')],[('prior','683','old','sha2')]))
    monkeypatch.setattr(investor_sweep.investor_eps, 'archived_statements', lambda sha: events.append(sha) or [])
    result = investor_sweep.backfill_statements()
    assert events == ['ALSM','HMKB','sha1','sha2']
    assert result['statements_checked'] == 2 and not result['errors']


def test_explicit_market_backfill_retries_only_missing_originals(monkeypatch, tmp_path):
    import ifrs_financials
    from catalogue import sources
    from financial_ingestion import documents, investor_sweep, store
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setenv('FINANCIAL_ARTIFACT_DIR', str(tmp_path / 'files'))
    url = 'https://openinfo.uz/media/msfo/unavailable.pdf'
    with store.transaction() as c:
        c.execute("INSERT INTO catalog_companies(ticker,org_id,company_name) VALUES ('BIOK','396','Biokimyo')")
        source = documents.register(c, org_id='396', ticker='BIOK', url=url, category='MSFO',
                                    processor='test', metadata={'status':'approved','period_type':'annual'})
    store.fail(store.claim(source_id=source, stages=('FETCH',)), 'Old upstream failure', max_attempts=1)
    monkeypatch.setattr(sources, '_fetch_main_results', lambda *args: ([], None))
    downloads = []
    monkeypatch.setattr(ifrs_financials, 'download_pdf',lambda url, **kw: downloads.append(url) or b'%PDF-recovered')
    monkeypatch.setattr(investor_sweep.investor_eps, 'archived_statements', lambda sha: [])
    for _ in range(2):
        result = investor_sweep.backfill_statements()
        assert not result['errors'] and result['statements_checked'] == 1
    assert downloads == [url]


@pytest.mark.parametrize(('org', 'ticker', 'filing_id', 'sha', 'filename', 'expected', 'page', 'year', 'scope'), [
    ('102', 'UZMT', 3216, '63db7b9ada8b30c5ccffe4f0074853e0dfc1fd0f48ace31ed60768dfa6345fda',
     '0ed3ebbe-7cf3-4716-a38c-2c0e9ec6a848.pdf', 1.25, 6, '2025', 'consolidated'),
    ('102', 'UZMT', 2970, '0711b3bc6b8e91fa62305f7af984c67100eb11a1dfc10ec3230b95933b911494',
     '0cf11785-0a35-4351-90ab-75d51a0f0b4a.pdf', 1.16, 6, '2024', 'consolidated'),
    ('102', 'UZMT', 2799, '7acaeecd409c2d82d99ab641a8eddb539b20c8c3580cac1beb0bfa1409e5d4f2',
     'Report_for_the_year_end_2023_full-4-11.pdf', 1.23, 6, '2023', 'consolidated'),
    ('638', 'UZAL', 3195, '62230b7098b396f816dbdb6b0ed692f37de570c673c079f9ade86707fb593d6c',
     '034056eb-8d01-4b1c-90c3-3a7f2044857f.pdf', 12.02, 7, '2025', 'separate'),
    ('382', 'BECM', 1980, 'd89648811c38b63c85f2cd9b433a0a6aa37a98354e8379b583629e96d55971fc',
     'Бекабадцемент_аудиторское_заключение_по_МСФО_за_2020_г.pdf', 182352.11, 4, '2020', 'separate'),
    ('25', 'INFB', 3253, '8eb36b0233e41e4374b0ba4695a4fe6d7445892eecbea5a481a22add820afe69',
     'e8d1ecd9-4c66-4a09-9b93-14c4eee1b984.pdf', 152.0, 9, '2025', 'consolidated'),
    ('23', 'BRBN', 3054, 'b9cd62318741c392beff34e8bdbe1296fe525fe4f901775250e25355776229be',
     '511b0950-b70c-4e94-b63b-13ca4bcdda0e.pdf', -22.0, 10, '2024', 'consolidated'),
    ('667', 'UPOS', 2036, '8255931d1003d3fd149c29954eea8221fe8c9872d58ec3ef2cbed6bca63ca95c',
     'Заключение_аудитора_и_отчеты_по_МСФО_за_2020_год.pdf', -100.0, 4, '2020', 'separate'),
    ('20', 'MCBA', 1774, '6bafe683a4dd9a8493fbe5f12b32afdfe3e8ca7234e08c13a17f62e880779fe3',
     'AuditReport2019.pdf', 18.18, 63, '2019', 'separate'),
    ('9', 'UNVB', 3169, '87151d9fda000c939d1b601612203006622d7dfa4bec0205c3210331f1be08d3',
     '358564ec-ac5d-4322-bd2d-26c346f539f2.pdf', 2320.84, 52, '2025', 'separate'),
    ('9', 'UNVB', 2911, '1873b7c5dbbdaf3e3cb28954e54ecaf12b5b228ee73bbfd09d4987e9f95076a5',
     '8064713f-ee9b-4c95-8e89-2448d7dce1a5.pdf', 1874.72, 52, '2024', 'separate'),
    ('24', 'TRSB', 3144, '7c7baf1fbf5974b5ebb082bee49fc9b010d7dfeb936513bb1bef22f24d54eae6',
     'e65e3138-844f-4693-a602-df39cf64be6d.pdf', 852.46, 11, '2025', 'consolidated'),
    ('636', 'DORI', 1477, 'e99df2769f8f55a26a28798ff3ed1b1c8dc1a1942a1ef622ad5a1ce44542f195',
     'Заключение_аудитора_по_МСФО_за_2018_г..pdf', 760.0, 6, '2018', 'separate'),
    ('576', 'UZML', 791, '2ef26a27d1f4a6edfc26614a6275bdf75171dc6d7b3ebfbb84bc66d3176493a2',
     'МСФО_-_отчет_за_2016..pdf', 710.0, 9, '2016', 'separate'),
    ('26', 'DRBK', 3244, 'fbd1d12d29f8f710c9e130d6a26f5824fe6a02206c6cb33586ff6478526b8a09',
     '2d2307d8-351b-4348-b76d-020e6ede93d1.pdf', 5663, 9, '2025', 'separate'),
    ('26', 'DRBK', 2824, 'd65a9a56b89ea5dc8c8f5ae3397f3bdb1a1a255a008a497d8055d08baf60b730',
     'Davrbank_FS_RU_2023.pdf', 3891.48, 53, '2023', 'separate'),
    ('666', 'UZTL', 3247, 'b9f77bd6bdfa283dbdf2bba863cc34c45cb07e6c46f9d53eb6e543ac9ae64efb',
     '7e7924bc-31df-4729-aa34-9499f7bdb516.pdf', 2215, 57, '2025', 'consolidated'),
    ('17', 'IPTB', 3335, '10a865f60a680744891049210eb4a54b68f26457accfc06cd9717c29d5578acd',
     '75f067b6-58c4-4f79-a7c1-94a7cfe4da5b.pdf', .53, 53, '2025', 'consolidated'),
    ('553', 'EQQU', 1133, '8948e986b9e3a412a8535d28ed9a552beded2dd9475c1a8df3cc135135f2baa2',
     'MSFO_2017.PDF', 15880, 4, '2017', 'consolidated'),
    ('19', 'AGBA', 3267, 'ab8e0077157f1ae51fd20fb6692e30e99578f2c5e37c1180dc2222a6596f41ad',
     '203c8cbb-bd8c-40a1-b0fc-69d78024f00f.pdf', 9, 9, '2025', 'consolidated'),
    ('28', 'IPKY', 3199, '97b5fe2f334e9316ec8392e431d542aafec34a7a5c161133e17afaee4244052f',
     'fe4cd9ed-d46a-46d4-b61f-e39ea6d7fa3a.pdf', 14.71, 10, '2025', 'consolidated'),
    ('16', 'ORFI', 3231, 'c49834e33ab311a22b69968d337a55b2d0e8158524841f16a96148d87a3ceb98',
     'decd2e97-107c-44a9-9ac7-5bdc5d68d2b5.pdf', 480, 9, '2025', 'consolidated'),
    ('22', 'TNBN', 3238, '7a868240e53231377dc2966905ad19faafe1cf3c63d0f2f585393c9739dcc878',
     '93a90ff4-a26f-4a61-b729-9dc699539692.pdf', 19, 10, '2025', 'consolidated'),
    ('446', 'KSCM', 2352, 'ca0dcdf18ce7942f941c6da79e3c4ebbdb14bb79676b98c3b705afdbf4725548',
     'Отчет_по_МСФО_по_итогам_2021_года.pdf', 73437, 2, '2021', 'separate'),
    ('702', 'UTGA', 2983, 'd244dd16d0acf6416825aa7403a73eba8e69e0a319d020c949cddbfc5fd8443a',
     '23476a8d-7661-407c-b062-4e4cbe68c775.pdf', 12759, 33, '2024', 'consolidated'),
    ('383', 'UZMK', 2796, '638f24391a957739db754682c8139b4f69c5e91f7ef8881ae876de33e80f2e66',
     'UMK_IFRS_FS_2023_eng.pdf', 1471, 8, '2023', 'consolidated'),
    ('30', 'SQBN', 3077, '2d85eea4d1c28a09500eb40327b03fb0f60bca311f1aee4471c998ca889591ce',
     'e873c921-48bf-4fa3-8865-1f24d35f0d37.pdf', 4.58, 76, '2024', 'consolidated'),
    ('80', 'UTHK', 1125, '7ef815928eef97e871fd30ee90b869f59246133e649edbb1cae31d8d05fcab54',
     'МСФО-2017_juGSVoD.pdf', 2115, 7, '2015', 'consolidated'),
    ('80', 'UTHK', 672, 'cc526fb95a8b5af03eb8e369a372b9533b97aea9b0c54a6ed87b32752850a24f',
     'MSFO_PG7LkTf.pdf', 3828, 6, '2014', 'consolidated'),
    ('717', 'URTS', 1874, '492350d2f0f467e7da7c4e6818d531b96ca01f09b72c8dd19909482f262f830d',
     '31_03_2020_Отчет_и_аудиторское_заключение_по_МСФО_2019_с_раскрытиями_compressed.pdf', 3260.07, 26, '2019', 'separate')])
def test_reviewed_ordinary_eps_requires_same_approved_openinfo_pdf(
        monkeypatch, tmp_path, org, ticker, filing_id, sha, filename, expected, page, year, scope):
    from financial_ingestion import documents, investor_eps, store
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'review.db'))
    monkeypatch.setenv('FINANCIAL_ARTIFACT_DIR', str(tmp_path))
    url = 'https://openinfo.uz/media/msfo/' + filename
    meta = dict(id=filing_id, organization_id=int(org), organization_name=ticker, status='approved',
                pdf_url=url, report_form='MSFO', period_type='annual', published_at='2026-10-20')
    with store.transaction() as conn:
        source = documents.register(conn, org_id=org, ticker=ticker, url=url, category='MSFO', processor='test', metadata=meta)
    def read():
        return investor_eps.official_eps(org, '2026-09-30', '2026-11-23', 'separate')
    documents.fetch_job(store.claim(stages=('FETCH',), source_id=source), 'test', fetch=lambda _: b'%PDF-test')
    assert read() is None
    with store.transaction() as conn:
        documents.register(conn, org_id=org, ticker=ticker, url=url, category='MSFO', processor='test',
                           metadata=meta, refresh_days=0)
    monkeypatch.setattr(documents, 'archive', lambda payload: (sha, sha + '.pdf'))
    documents.fetch_job(store.claim(stages=('FETCH',), source_id=source), 'test', fetch=lambda _: b'%PDF-reviewed')
    filing = read() or {}
    assert filing.get('value') == expected
    source_unit = 'USD_per_share' if ticker == 'UZMT' else 'UZS_per_share'
    assert filing['unit'] == source_unit
    assert (filing['scope'], filing['period'], filing['source_url'], filing['page']) == (scope, year, url, page)
    with store.transaction() as conn:
        documents.register(conn, org_id=org, ticker=ticker, url=url, category='MSFO', processor='test',
                           metadata={**meta, 'status': 'withdrawn'})
    assert read() is None

def test_grbk_eps_uses_the_signed_ordinary_share_note_with_its_own_year(monkeypatch):
    from financial_ingestion import disclosures, investor_eps

    url = 'https://openinfo.uz/media/audit_conclusion/Tashqi_audit_hisoboti_2023.pdf'
    def matches_source(conn, **identity):
        return identity == dict(
            org_id='11', api_path='/reports/bank/annual/338/', category='Audition', url=url,
            pdf_sha='dba49cfcb8ee09b44e24b556e7ce5a1746ea88033853e3416346ef4acd73c0e8',
            parent_sha='b871a78e4edd78bd16976d104c739f3e13bd5b4a93cb00e0e92e8ed9a7e8cd4d',
        )

    monkeypatch.setattr(disclosures, 'reviewed_attachment', matches_source)
    def read(end, cutoff):
        return {fact['period']: fact for fact in investor_eps._reviewed_eps(None, '11', end, cutoff)}

    assert read('2023-12-31', '2024-07-11') == {}
    facts = read('2023-12-31', '2024-07-12')
    assert set(facts) == {'2022', '2023'}
    for year, value in [('2023', -27.74), ('2022', 5.75)]:
        assert facts[year] == dict(period=year, standard='ifrs', scope='separate', value=value,
                                   unit='UZS_per_share', source_url=url, page=52)
    assert set(read('2022-12-31', '2024-07-12')) == {'2022'}
