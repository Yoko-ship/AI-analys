import asyncio
from datetime import date
import pytest
from server.terminal import service, analytics, cbu


def test_screener_joins_official_bank_data_without_changing_report_period(monkeypatch):
    monkeypatch.setattr(service,'universe',lambda:[{'ticker':'AGBA','kind':'bank','name':'Agrobank'}])
    monkeypatch.setattr(service,'market_context',lambda:{'AGBA':{'market_cap':200,'price':10}})
    monkeypatch.setattr(cbu,'context',lambda:{'banks':{'AGBA':{'npl':{'npl_pct':3.4,'date':'2026-09-01','source_url':'https://cbu.uz/npl'}}},'deposit':{'value':17.2,'period':'2026-08','source_url':'https://cbu.uz/rates'},'sector':{},'fsi':[]})
    async def financials(*args):return {'periods':['2025'],'series':{},'standard':'NSBU'}
    monkeypatch.setattr(service,'financial_series',financials)
    result=asyncio.run(service.screener())
    assert result['rows'][0]['npl']==3.4
    assert result['rows'][0]['period']=='2025'
    assert result['rows'][0]['cbu']['npl']['date']=='2026-09-01'
    assert result['deposit_rate']==17.2 and result['deposit']['period']=='2026-08'


def test_dividend_comparison_uses_recent_decision_and_never_sums_overlapping_periods():
    items=[{'ordinary_amount':100,'decision_date':'2024-06-01'}, {'ordinary_amount':20,'decision_date':'2026-06-01'}, {'ordinary_amount':10,'decision_date':'2026-03-01'}]
    result=analytics.dividend(items,100,today=date(2026,10,23))
    assert result['dy']==20 and result['basis']=='latest_decision'
    assert analytics.dividend(items[:1],100,today=date(2026,10,23))['dy'] is None
    assert analytics.dividend(items,0)['dy'] is None


def test_screener_respects_catalog_visibility_and_newer_quotes(monkeypatch):
    import company_imports
    import catalogue.market_store as market
    monkeypatch.setattr(service,'get_securities_map',lambda:{'AGBA':{'type':'stock','isin':'UZ1'},'HMKB':{'type':'stock'}})
    monkeypatch.setattr(service.filings,'list_companies_with_stats',lambda:[{'ticker':'AGBA'},{'ticker':'HMKB'}])
    monkeypatch.setattr(service.organization,'filing_org_types',lambda stocks:{})
    monkeypatch.setattr(company_imports,'approved_metadata_map',lambda:{'AGBA':{'catalog_visible':0}})
    assert [r['ticker'] for r in service.universe()]==['HMKB']
    monkeypatch.setattr(market,'get_all_listings',lambda:{'AGBA':{'last_price':10,'last_trade_date':'2026-09-01'}})
    monkeypatch.setattr(market,'get_all_quotes',lambda:{'UZ1':{'close_price':12,'trade_date':'2026-10-01'}})
    assert service.market_context()['AGBA']['price']==12


def test_issuer_growth_uses_stored_official_inflation_and_fx(monkeypatch):
    from server.currency import history
    annual={'periods':['2022','2025'],'series':{'net_profit':{'values':{'2022':100,'2025':133.1}}}}
    async def financials(*args):return annual if args[1]=='annual' else {'series':{}}
    monkeypatch.setattr(service,'financial_series',financials)
    monkeypatch.setattr(service.organization,'organization_kind',lambda t:'bank')
    monkeypatch.setattr(service.filings,'get_company_index',lambda t:{})
    monkeypatch.setattr(cbu,'context',lambda:{'banks':{},'inflation':{'2023':10,'2024':10,'2025':10}})
    monkeypatch.setattr(history,'cached_usd',lambda:{'2022':10000,'2025':11000},raising=False)
    result=asyncio.run(service.issuer('AGBA'))
    growth=next(r for r in result['growth'] if r['field']=='net_profit' and r['years']==3)
    assert growth['real']==pytest.approx(0,abs=1e-10)
    assert growth['usd']<growth['nominal']


def test_issuer_dividend_and_earnings_yield_share_dated_deposit_context(monkeypatch):
    import dividends
    from server.currency import history
    async def financials(*args):return {'periods':['2025'],'series':{'net_profit':{'values':{'2025':20}}}}
    monkeypatch.setattr(service,'financial_series',financials)
    monkeypatch.setattr(service,'market_context',lambda:{'AGBA':{'market_cap':100,'price':10,'market_date':'2026-10-01'}})
    monkeypatch.setattr(service.organization,'organization_kind',lambda t:'bank')
    monkeypatch.setattr(service.filings,'get_company_index',lambda t:{})
    monkeypatch.setattr(cbu,'context',lambda:{'banks':{},'deposit':{'period':'2026-08','value':17.2}})
    monkeypatch.setattr(history,'cached_usd',lambda:{})
    monkeypatch.setattr(dividends,'read_snapshot',lambda ticker:[{'ordinary_amount':2,'decision_date':date.today().isoformat()}])
    result=asyncio.run(service.issuer('AGBA'))
    assert result['snapshot']['ep']==20 and result['snapshot']['dy']==20
    assert result['deposit']['period']=='2026-08'


def test_bank_comparison_exposes_dated_market_shares_and_structure():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/cbu_terminal_202609.json').read_text())
    bank={kind:next(r for r in cbu.parse_bank_rows(fixture[kind]['rows'],kind,fixture[kind]['source_url'])['rows'] if r['ticker']=='AGBA') for kind in ('npl','main','structure')}
    result=service.bank_metrics(bank)
    assert result['cbu_assets_share_pct']==bank['main']['assets_share_pct']
    assert result['cbu_household_loans_bn']==bank['structure']['household_loans_bn']
    assert result['cbu_company_deposits_bn']==bank['structure']['company_deposits_bn']
    assert service.bank_metrics({})['cbu_assets_share_pct'] is None


def test_issuer_overview_exposes_cbu_history_without_mixing_annual_periods(monkeypatch):
    from server.currency import history
    observations=[{'ticker':'HMKB','date':'2026-09-01','assets_rank':8,'assets_bn':43114.828277036795}]
    async def financials(*args):return {'periods':['2025'],'series':{},'standard':'NSBU'}
    monkeypatch.setattr(service,'financial_series',financials)
    monkeypatch.setattr(service,'market_context',lambda:{})
    monkeypatch.setattr(service.organization,'organization_kind',lambda t:'bank')
    monkeypatch.setattr(service.filings,'get_company_index',lambda t:{})
    monkeypatch.setattr(cbu,'context',lambda:{'banks':{'HMKB':{'main':observations[-1]}}})
    monkeypatch.setattr(cbu,'monthly_bank_history',lambda ticker:observations,raising=False)
    monkeypatch.setattr(history,'cached_usd',lambda:{})
    monkeypatch.setattr(service.dividends,'read_snapshot',lambda ticker:[])
    result=asyncio.run(service.issuer('HMKB'))
    assert result['snapshot']['period']=='2025'
    assert result['cbu_history']==observations


def test_market_context_excludes_confirmed_inactive_preferred_and_stale_dividend_price(monkeypatch):
    import catalogue.market_store as market
    from datetime import timedelta
    today=date.today().isoformat();stale=(date.today()-timedelta(days=365)).isoformat()
    securities={'UZAS':{'isin':'UZ7045570007','issuer_id':'669','share_type':'ordinary'},
                'UZASP':{'isin':'UZ704557K016','issuer_id':'669','is_preferred':True,'share_type':'preferred'},
                'ORFI':{'isin':'UZ7055870008','issuer_id':'16','share_type':'ordinary'}}
    listings={'UZAS':{'shares_outstanding':33198274,'last_price':178000,'last_trade_date':today},
              'UZASP':{'shares_outstanding':20000,'last_price':13000,'last_trade_date':stale},
              'ORFI':{'shares_outstanding':2867124015,'last_price':573.95,'last_trade_date':'2021-07-27'}}
    monkeypatch.setattr(service,'get_securities_map',lambda:securities)
    monkeypatch.setattr(market,'get_all_listings',lambda:listings)
    monkeypatch.setattr(market,'get_all_quotes',lambda:{})
    result=service.market_context()
    assert result['UZAS']['market_cap']==33198274*178000
    assert result['ORFI']['price'] is None
    assert result['ORFI']['market_date']=='2021-07-27'
    assert result['UZAS']['excluded_classes']==['UZASP']


def test_real_uzas_quote_supplies_missing_listing_shares_without_inventing_orfi_yield(monkeypatch):
    import json,public_contract
    from pathlib import Path
    import catalogue.market_store as market
    records=json.loads((Path(__file__).parent/'fixtures/terminal_market_inputs_20261023.json').read_text())
    rows={r['row']['ticker']:r['row'] for r in records}
    quotes={r['row']['isin']:r['quote'] for r in records if r['quote']}
    monkeypatch.setattr(service,'get_securities_map',lambda:rows)
    monkeypatch.setattr(market,'get_all_listings',lambda:rows)
    monkeypatch.setattr(market,'get_all_quotes',lambda:quotes)
    checked=public_contract.market_class_input
    monkeypatch.setattr(public_contract,'market_class_input',lambda row:checked(row,reference_date=date(2026,10,23)))
    result=service.market_context()
    assert result['UZAS']['market_cap']==pytest.approx(33198274*178000+20000*13000)
    assert result['UTGA']['market_cap']==pytest.approx(622631949*700000+3145123*21900)
    assert result['UVGT']['market_cap']==pytest.approx(2968227*89999)
    assert result['OCBK']['market_cap'] is None # June trade is stale
    assert result['ORFI']['price'] is None # 2021 quote cannot price a 2026 dividend
