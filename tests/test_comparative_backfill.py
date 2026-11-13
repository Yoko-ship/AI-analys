"""A missing annual is filled from the next annual's prior-year column
(docs/catalog-terminal/02-data.md, R-D4). Figures are the real filings'."""
import pytest

import catalogue.financial_store as catalogue_financial_store
from financial_ingestion import comparative

# BECM's FY2024 annual (jsc/annual/5406) printing FY2023 beside it, thousands.
BECM_FY2024 = {
    "org_type": "jsc",
    "prior": {"revenue": 636_875_363.0, "gross_profit": 120_000_000.0,
              "net_income": 94_897_078.0, "operating_income": 101_000_000.0},
    "balance": {"assets_start": 759_692_384.0, "equity_start": 600_000_000.0,
                "assets_end": 800_000_000.0, "equity_end": 650_000_000.0},
}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))


def test_the_prior_year_column_becomes_that_years_figures():
    values = comparative.comparative_values(BECM_FY2024)
    assert values["revenue"] == 636_875_363.0 and values["net_income"] == 94_897_078.0
    assert values["total_assets"] == 759_692_384.0
    assert values["total_liabilities"] == 159_692_384.0


def test_the_bank_form_has_no_comparative():
    assert comparative.comparative_values({**BECM_FY2024, "org_type": "bank"}) is None


def test_an_unfilled_opening_balance_is_a_gap_not_a_nought():
    metrics = {**BECM_FY2024, "balance": {"assets_start": 0.0, "equity_start": 0.0}}
    values = comparative.comparative_values(metrics)
    assert values["revenue"] == 636_875_363.0
    assert values["total_assets"] is None and values["total_liabilities"] is None


def test_a_comparative_of_noughts_states_nothing():
    metrics = {"org_type": "jsc", "prior": {"revenue": 0.0, "net_income": 0.0}, "balance": {}}
    assert comparative.comparative_values(metrics) is None


def _filed(ticker, year, assets):
    catalogue_financial_store.upsert_financials_cache(
        ticker, "NSBU", year, 0, {"revenue": 500_000_000.0, "net_income": 50_000_000.0,
                                  "total_assets": assets, "total_equity": assets / 2})


def test_only_a_year_with_a_usable_filing_after_it_is_missing(catalog):
    _filed("BECM", 2022, 700_000_000.0)
    _filed("BECM", 2024, 800_000_000.0)
    # 2021: junk filing (line numbers as amounts) followed by a real 2022.
    catalogue_financial_store.upsert_financials_cache("BECM", "NSBU", 2021, 0,
                                                      {"revenue": 10.0, "net_income": 270.0})
    assert comparative.missing_years(["BECM"], last_fy=2025) == [2021, 2023]


def test_the_backfill_stores_the_year_with_its_source(catalog, monkeypatch):
    _filed("BECM", 2022, 700_000_000.0)
    _filed("BECM", 2024, 800_000_000.0)
    monkeypatch.setattr(comparative, "missing_years", lambda aliases: [2023])
    monkeypatch.setattr(comparative, "_annual_detail",
                        lambda org, year: ({"object_id": 5406, "org_type": "jsc", "pub_date": "2025-06-26"}, {"x": 1}))
    import openinfo_reconcile
    monkeypatch.setattr(openinfo_reconcile, "extract_metrics", lambda detail: BECM_FY2024)
    events = []
    filled = comparative.backfill_issuer("1",  ["BECM", "BECMP"], journal=lambda e, **f: events.append((e, f)))
    assert filled == [2023]
    stored = comparative.comparative_years("BECMP")["2023"]
    assert stored["revenue"] == 636_875_363.0
    assert stored["source"]["year"] == 2024 and stored["source"]["object_id"] == 5406
    assert comparative.source_url(stored["source"]) == "https://openinfo.uz/reports/jsc/annual/5406"
    assert events[0][0] == "year_backfill" and events[0][1]["period"] == "2023"


def test_existing_year_is_checked_for_restatement_without_overwriting_it(catalog, monkeypatch):
    from server.terminal import journal
    _filed('BECM',2023,759_692_384)
    _filed('BECM',2024,800_000_000)
    monkeypatch.setattr(comparative,'missing_years',lambda aliases:[])
    monkeypatch.setattr(comparative,'_annual_detail',lambda org,year:({'object_id':5406,'org_type':'jsc','pub_date':'2025-06-26'},{'x':1}))
    import openinfo_reconcile
    monkeypatch.setattr(openinfo_reconcile,'extract_metrics',lambda detail:BECM_FY2024)
    for _ in range(2):
        assert comparative.backfill_issuer('1',['BECM'],journal=journal.emit)==[]
    events=journal.events(event='restatement')
    assert events['total']==1
    assert events['items'][0]['period']=='2023'
    assert events['items'][0]['source_url'].endswith('/5406')
    c=comparative._connect()
    assert c.execute("SELECT net_income FROM catalog_financials WHERE ticker='BECM' AND year=2023").fetchone()[0]==50_000_000
    c.close()


def test_restatement_threshold_is_strict_and_zero_base_is_explicit():
    from financial_ingestion.comparative import restated_fields
    assert restated_fields({'net_income':100},{'net_income':101})=={}
    assert restated_fields({'net_income':-100},{'net_income':-101})=={}
    assert restated_fields({'net_income':0},{'net_income':0})=={}
    assert restated_fields({'net_income':None},{'net_income':100})=={}
    assert restated_fields({'net_income':100},{'net_income':101.01})['net_income']['change_pct']>1
    assert restated_fields({'net_income':0},{'net_income':100})['net_income']['change_pct'] is None


@pytest.mark.parametrize('corruption', [None, 'wrong_quarter', 'wrong_year'])
def test_history_recovers_uztl_missing_half_year_from_filed_comparison(catalog, monkeypatch, corruption):
    """Production 2026-11-13: no UZTL 2021Q2, though 2022Q2 states it."""
    import json
    from pathlib import Path
    import catalogue.filings as filings
    import catalogue.history as catalog_history
    import catalogue.snapshots as snapshots
    import catalogue.storage as storage
    from financial_ingestion import nsbu_history
    import openinfo_reconcile as oi

    detail = json.loads(Path('tests/fixtures/uztl-2022q2-comparative.json').read_text())
    if corruption == 'wrong_quarter':
        detail['quarter_no'] = '2'
    elif corruption == 'wrong_year':
        detail['reporting_year'] = '2021-06-30'
    c = storage.get_catalog_conn()
    with c:
        for ticker in ('UZTL', 'UZTLP'):
            c.execute('INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES(?,?,?)',
                      (ticker, 'Uztelecom', '666'))
        filings._upsert_report(c, 'UZTL', report_form='NSBU', period_type='quarter', year=2022, quarter=2,
            title='Half-year', published_at=detail['pub_date'], pdf_url=None,
            excel_url='https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=jsc&report_id=12860&lang=ru',
            excel_url_form1=None, openinfo_report_id='12860', object_id=None)
    c.close()
    catalogue_financial_store.upsert_financials_cache('UZTL', 'NSBU', 2022, 2,
        {'revenue': 2995737539, 'net_income': 280500312})
    monkeypatch.setattr(nsbu_history, '_periods', lambda aliases: {})
    monkeypatch.setattr(catalog_history, 'harvest_historical_quarters', lambda *a, **kw: {'added': 0, 'errors': []})
    monkeypatch.setattr(comparative, 'backfill_issuer', lambda *a, **kw: [])
    monkeypatch.setattr(oi, 'fetch_detail', lambda cand: detail)
    result = nsbu_history.run(['UZTL'])
    if corruption:
        assert 'does not match' in result['errors'][0]['error']
        assert '2021Q2' not in snapshots.get_financials_series_quarterly('UZTL')
        return
    for ticker in ('UZTL', 'UZTLP'):
        series = snapshots.get_financials_series_quarterly(ticker)
        recovered = series.get('2021Q2', {})
        assert recovered.get('net_income') == 333905938
        assert recovered['revenue'] == 2561309007
        assert 'total_assets' not in recovered  # opening balance is January, not H1
        assert recovered['comparative_sources']['net_income']['source_url'] == 'https://openinfo.uz/reports/jsc/quarter/12860'
    monkeypatch.setattr(oi, 'fetch_detail', lambda cand: pytest.fail('Unchanged sources must resume without downloading'))
    assert nsbu_history.run(['UZTL'])['quarter_backfilled'] == 0
    # A subsequently imported original takes precedence, including a real zero.
    catalogue_financial_store.upsert_financials_cache('UZTL', 'NSBU', 2021, 2,
        {'revenue': 2561309007, 'net_income': 0})
    assert snapshots.get_financials_series_quarterly('UZTL')['2021Q2']['net_income'] == 0


def test_broken_microfinance_excel_does_not_hide_published_structured_income(catalog, monkeypatch):
    import json
    from pathlib import Path
    import catalogue.filings as filings
    import catalogue.history as catalog_history
    import catalogue.snapshots as snapshots
    import catalogue.storage as storage
    from financial_ingestion import nsbu_history
    import openinfo_reconcile as oi

    detail = json.loads(Path('tests/fixtures/acmt-2026q2-structured.json').read_text())
    c = storage.get_catalog_conn()
    with c:
        c.execute('INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES(?,?,?)',
                  ('ACMT1B2', 'AGAT Credit', '1058'))
        filings._upsert_report(c, 'ACMT1B2', report_form='NSBU', period_type='quarter', year=2026, quarter=2,
            title='Half-year', published_at=detail['pub_date'], pdf_url=None,
            excel_url='https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=microfinance&report_id=56&lang=ru',
            excel_url_form1=None, openinfo_report_id='56', object_id=None)
    c.close()
    monkeypatch.setattr(nsbu_history, '_periods', lambda aliases: {})
    monkeypatch.setattr(catalog_history, 'harvest_historical_quarters', lambda *a, **kw: {'added': 0, 'errors': []})
    monkeypatch.setattr(comparative, 'backfill_issuer', lambda *a, **kw: [])
    monkeypatch.setattr(oi, 'fetch_detail', lambda cand: detail)
    nsbu_history.run(['ACMT1B2'])
    current = snapshots.get_financials_series_quarterly('ACMT1B2').get('2026Q2', {})
    assert current.get('net_income') == 3523955
    assert current['revenue'] == 48779406
    assert current['supplemental_sources']['net_income']['source_url'].endswith('/microfinance/quarter/56')
    # A bank-form single-column amount is never a prior-year comparison.
    assert '2025Q2' not in snapshots.get_financials_series_quarterly('ACMT1B2')
    monkeypatch.setattr(oi, 'fetch_detail', lambda cand: pytest.fail('Unchanged sources must resume without downloading'))
    assert nsbu_history.run(['ACMT1B2'])['structured_quarters'] == 0


def test_quarter_discovery_uses_structured_period_when_excel_export_fails(catalog, monkeypatch):
    import json
    from pathlib import Path
    import catalogue.history as history
    import catalogue.storage as storage
    import catalogue.snapshots as snapshots
    import openinfo_reconcile as oi
    detail = json.loads(Path('tests/fixtures/acmt-2026q2-structured.json').read_text())
    c = storage.get_catalog_conn()
    with c:
        c.execute('INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES(?,?,?)', ('ACMT1B2','AGAT Credit','1058'))
    c.close()
    monkeypatch.setattr(history,'unified_quarterly_records',lambda *a:[{
        'accounting_id':'56','org_type':'microfinance','pub_date':detail['pub_date'],'pdf_id':None,
        'excel_url':'https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=microfinance&report_id=56&lang=ru',
        'title':'Quarterly report'}])
    def broken(*a):
        raise RuntimeError('500 Server Error')
    monkeypatch.setattr(history,'_parse_workbook_uncached',broken)
    monkeypatch.setattr(oi,'fetch_detail',lambda *a:detail)
    discovered=history.harvest_historical_quarters('ACMT1B2',pace=0,publish=False)
    assert discovered['added']==1
    assert discovered['errors']==[]
    assert discovered['rows'][0]['year']==2026 and discovered['rows'][0]['quarter']==2
    assert snapshots.get_financials_series_quarterly('ACMT1B2').get('2026Q2',{}).get('net_income') is None
    from financial_ingestion.quarterly_comparative import backfill
    assert backfill('1058',['ACMT1B2'])['structured']==['2026Q2']
    assert snapshots.get_financials_series_quarterly('ACMT1B2')['2026Q2']['net_income']==3523955


def test_commercial_llc_filings_share_the_jsc_endpoint_without_losing_comparisons(catalog, monkeypatch):
    import json
    from pathlib import Path
    import catalogue.filings as filings
    import catalogue.snapshots as snapshots
    import catalogue.storage as storage
    from financial_ingestion import quarterly_comparative as recovery
    import openinfo_reconcile as oi
    detail=json.loads(Path('tests/fixtures/bfmt-2022q1-comparative.json').read_text())
    c=storage.get_catalog_conn()
    with c:
        c.execute('INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES(?,?,?)', ('BFMT3B4','Biznes Finans','922'))
        filings._upsert_report(c,'BFMT3B4',report_form='NSBU',period_type='quarter',year=2022,quarter=1,
            title='Quarterly report',published_at=detail['pub_date'],pdf_url=None,excel_url='https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=jsc&report_id=16658&lang=ru',
            excel_url_form1=None,openinfo_report_id='16658',object_id=None)
    c.close()
    monkeypatch.setattr(oi,'fetch_detail',lambda *a:detail)
    result=recovery.backfill('922',['BFMT3B4'])
    assert result['errors']==[]
    quarters=snapshots.get_financials_series_quarterly('BFMT3B4')
    assert quarters['2022Q1']['net_income']==3371321
    assert quarters['2021Q1']['net_income']==2105964
    assert 'total_assets' not in quarters['2021Q1']
