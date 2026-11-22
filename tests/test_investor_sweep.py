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
