import json
from pathlib import Path
import pytest
from server.terminal import cbu
from server.terminal import journal

FIXTURE=json.loads((Path(__file__).parent/'fixtures/cbu_terminal_202609.json').read_text())


def test_year_context_uses_real_historical_observations_without_latest_fallback(tmp_path,monkeypatch):
    monkeypatch.setenv('CBU_DATA_DB',str(tmp_path/'cbu.sqlite3'))
    historical=json.loads((Path(__file__).parent/'fixtures/cbu_terminal_2020.json').read_text())
    for fixture in (historical,FIXTURE):
        for kind in ('npl','structure'):
            dataset=cbu.parse_bank_rows(fixture[kind]['rows'],kind,fixture[kind]['source_url'])
            cbu.save(kind,dataset['date'],dataset)
    main=cbu.parse_bank_rows(FIXTURE['main']['rows'],'main',FIXTURE['main']['source_url'])
    cbu.save('main',main['date'],main)
    for day,value in [('2020-05-01',11),('2020-12-01',12),('2026-09-01',26)]:
        cbu.save('profitability',day,{'date':day,'metrics':{'roe':{'value':value}},'source_url':'https://cbu.uz/example'})
    cbu.save('rates','2026-08',[{'indicator':'FITD_NC_WA_PA','dimensions':{'FREQ':'M'},'period':p,'value':v}
                             for p,v in [('2020-10',10),('2020-12',12),('2026-08',26)]])
    old=cbu.context(year=2020)
    expected=cbu.parse_bank_rows(historical['npl']['rows'],'npl',historical['npl']['source_url'])
    agba=next(r for r in expected['rows'] if r['ticker']=='AGBA')
    assert old['banks']['AGBA']['npl']==agba
    assert old['banks']['AGBA']['structure']['date'].startswith('2020-')
    assert 'main' not in old['banks']['AGBA']
    assert old['sector_series']['profitability']['date']=='2020-12-01'
    assert old['deposit']['period']=='2020-12'
    absent=cbu.context(year=2024)
    assert absent['banks']=={} and absent['sector_series']=={} and absent['deposit'] is None
    assert cbu.context()['banks']['AGBA']['npl']['date']=='2026-09-01'


def test_bank_ranks_include_unlisted_banks_and_keep_missing_assets_unknown(monkeypatch):
    dataset=cbu.parse_bank_rows(FIXTURE['main']['rows'],'main',FIXTURE['main']['source_url'])
    monkeypatch.setattr(cbu,'latest',lambda kind:dataset if kind=='main' else None)
    banks=cbu.context()['banks']
    assert banks['AGBA']['main']['assets_rank']==2
    assert banks['HMKB']['main']['assets_rank']==8
    assert banks['HMKB']['main']['rank_population']==35
    next(row for row in dataset['rows'] if row['ticker']=='HMKB')['assets_bn']=None
    assert cbu.context()['banks']['HMKB']['main']['assets_rank'] is None


def test_bank_history_keeps_observation_dates_units_and_gaps(tmp_path,monkeypatch):
    from copy import deepcopy
    monkeypatch.setenv('CBU_DATA_DB',str(tmp_path/'cbu.sqlite3'))
    september=cbu.parse_bank_rows(FIXTURE['main']['rows'],'main',FIXTURE['main']['source_url'])
    july=deepcopy(september)
    july['date']='2026-07-01'
    for row in july['rows']:row['date']='2026-07-01'
    cbu.save('main',july['date'],july)
    cbu.save('main',september['date'],september)
    rows=cbu.monthly_bank_history('HMKB')
    assert [row['date'] for row in rows]==['2026-07-01','2026-09-01']
    assert rows[-1]['assets_bn']==pytest.approx(43114.828277036795)
    assert rows[-1]['assets_rank']==8
    assert rows[-1]['source_url']==september['source_url']
    assert cbu.monthly_bank_history('NOT_A_BANK')==[]


def test_all_seventeen_banks_match_official_september_npl():
    data=cbu.parse_bank_rows(FIXTURE['npl']['rows'],'npl',FIXTURE['npl']['source_url'])
    banks={r['ticker']:r for r in data['rows'] if r['ticker']}
    expected={'HMKB':1.4,'IPKY':1.8,'ORFI':1.9,'INFB':2.4,'UNVB':2.5,'DRBK':2.9,'IPTB':3.0,'SQBN':3.1,'AGBA':3.4,'TRSB':3.7,'ALKB':3.8,'TNBN':3.8,'TNGB':4.9,'BRBN':5.8,'GRBK':7.7,'MCBA':9.2,'OCBK':0.0}
    assert set(banks)==set(expected)
    assert data['date']=='2026-09-01'
    for ticker,expected_pct in expected.items():assert banks[ticker]['npl_pct']==pytest.approx(expected_pct,abs=.051)
    assert {t for t,r in banks.items() if r['npl_flag']}=={'BRBN','GRBK','MCBA'}
    assert len(data['rows'])>17 # unlisted banks retained for sector comparison


def test_headers_can_move_and_main_amounts_keep_their_unit():
    rows=[['New cover row'],*FIXTURE['main']['rows']]
    data=cbu.parse_bank_rows(rows,'main',FIXTURE['main']['source_url'])
    agba=next(r for r in data['rows'] if r['ticker']=='AGBA')
    assert agba['assets_bn']>100000
    assert 10<agba['assets_share_pct']<20
    assert data['unit']=='billion UZS'


def test_format_change_is_critical_and_replaces_nothing():
    with pytest.raises(cbu.FormatChanged): cbu.parse_bank_rows([['Wrong document']], 'npl','https://cbu.uz/file.xlsx')
    assert journal.events(event='load_format_changed')['total']==1


def test_structure_keeps_households_and_companies_separate():
    data=cbu.parse_bank_rows(FIXTURE['structure']['rows'],'structure',FIXTURE['structure']['source_url'])
    row=next(r for r in data['rows'] if r['ticker']=='AGBA')
    assert row['loans_bn']==pytest.approx(row['household_loans_bn']+row['company_loans_bn'])


def test_sdmx_rejects_html_and_preserves_series_dimensions():
    xml=b'<StructureSpecificData><DataSet><Series INDICATOR="FITD_NC_WA_PA" FREQ="M" UNIT_MULT="0"><Obs TIME_PERIOD="2026-08" OBS_VALUE="17.2"/></Series></DataSet></StructureSpecificData>'
    data=cbu.parse_sdmx(xml,'https://cbu.uz/rates.xml')
    assert data[0]['indicator']=='FITD_NC_WA_PA' and data[0]['value']==17.2
    assert data[0]['period']=='2026-08'
    with pytest.raises(cbu.FormatChanged):cbu.parse_sdmx(b'<html>Not Found</html>','https://cbu.uz/fsi.xml')


def test_inflation_uses_december_headline_not_core_or_partial_year():
    fixture=json.loads((Path(__file__).parent/'fixtures/cbu_inflation.json').read_text())
    records=cbu.parse_inflation(fixture['tables'][0],fixture['source_url'])
    annual=cbu.annual_inflation(records)
    assert annual['2025']==7.3
    assert '2026' not in annual
    assert records[-1]['source_url']==fixture['source_url']


def test_official_sector_spreadsheets_keep_percentage_units_and_both_dates():
    fixture=json.loads((Path(__file__).parent/'fixtures/cbu_sector_202609.json').read_text())
    data={k:cbu.parse_sector_rows(v['rows'],k,v['source_url']) for k,v in fixture.items()}
    assert data['capital']['metrics']['capital_adequacy']['value']==pytest.approx(18.321406)
    assert data['profitability']['metrics']['roe']['value']==pytest.approx(14.40088768)
    assert data['profitability']['metrics']['nim']['value']==pytest.approx(4.2100069)
    assert data['liquidity']['date']=='2026-09-01'
    industry=next(r for r in data['industry']['rows'] if r['name']=='Промышленность')
    assert industry['observations']['2026-09-01']==pytest.approx(132372.391442)
    assert industry['unit']=='billion UZS'
    assert len(industry['observations'])==2


def test_sdmx_links_are_discovered_from_official_dataset_titles():
    html='''<table><tr><td>Interest Rates</td><td><a href="/sdmx/INR_Uzbekistan_Online_STA.xml">SDMX File</a></td></tr>
    <tr><td>Financial Soundness Indicators</td><td><a href="/sdmx/FSD_Uzbekistan_STA_IMF.xml">SDMX File</a></td></tr></table>'''
    links=cbu.discover_sdmx(html)
    assert links['fsi']=='https://cbu.uz/sdmx/FSD_Uzbekistan_STA_IMF.xml'
    assert links['rates'].endswith('/INR_Uzbekistan_Online_STA.xml')
    with pytest.raises(cbu.FormatChanged):cbu.discover_sdmx(html.replace('/sdmx/FSD_', 'https://untrusted.example/FSD_'))


def test_inflation_pagination_does_not_stop_at_a_truncated_navigation(monkeypatch):
    import requests
    from types import SimpleNamespace
    pages=[];saved=[]
    header='<tr><th>Date</th><th>Headline inflation compared to the same month of the previous year (%)</th></tr>'
    def get(url,**kw):
        pages.append(url)
        from urllib.parse import urlparse,parse_qs
        page=int(parse_qs(urlparse(url).query).get('lists_list_elements_983',['page-1'])[0].split('-')[-1])
        year=2026-page
        # Navigation only offers page 2, even though pages 3/4 remain available.
        rows=f'<tr><td>01.12.{year}</td><td>10.0</td></tr>' if page<=6 else ''
        return SimpleNamespace(text=f'<table>{header}{rows}</table><a href="?lists_list_elements_983=page-2">2</a>',raise_for_status=lambda:None)
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr(cbu,'latest',lambda kind:[])
    monkeypatch.setattr(cbu,'save',lambda *args:saved.append(args))
    result=cbu.sync_inflation()
    assert {'2020','2021','2022','2023','2024','2025'}<=set(cbu.annual_inflation(result))
    assert len(pages)<=10


def test_historical_cbu_headers_preserve_2020_observations():
    historical=json.loads((Path(__file__).parent/'fixtures/cbu_terminal_2020.json').read_text())
    npl=cbu.parse_bank_rows(historical['npl']['rows'],'npl',historical['npl']['source_url'])
    sqbn=next(r for r in npl['rows'] if r['ticker']=='SQBN')
    assert npl['date']=='2020-05-01'
    assert sqbn['npl_pct']==pytest.approx(1.128261786)
    structure=cbu.parse_bank_rows(historical['structure']['rows'],'structure',historical['structure']['source_url'])
    row=next(r for r in structure['rows'] if r['ticker']=='HMKB')
    assert row['deposits_bn']==pytest.approx(3165.2331595384303)
    assert row['deposits_bn']==pytest.approx(row['household_deposits_bn']+row['company_deposits_bn'])


def test_unfilled_cells_for_new_banks_remain_missing_without_dropping_sector():
    from copy import deepcopy
    rows=deepcopy(FIXTURE['main']['rows'])
    header=next(r for r in rows if any('наименованиебанка' in cbu.norm(c) for c in r))
    assets=next(i for i,c in enumerate(header) if cbu.norm(c).startswith('актив'))
    target=next(r for r in rows if any(cbu.norm(c)=='агробанк' for c in r))
    target[assets]=None;target[assets+1]='-'
    data=cbu.parse_bank_rows(rows,'main',FIXTURE['main']['source_url'])
    assert next(r for r in data['rows'] if r['ticker']=='AGBA')['assets_bn'] is None
    assert next(r for r in data['rows'] if r['ticker']=='AGBA')['assets_share_pct'] is None
    assert data['sector']['assets_bn']>0
    target[assets]=-1
    with pytest.raises(cbu.FormatChanged):cbu.parse_bank_rows(rows,'main',FIXTURE['main']['source_url'])


def test_reviewed_annual_inflation_uses_cbu_report_for_portal_discrepancy():
    # The current portal says 12.2; CBU's Q4 2022 report, p.15, states 12.3.
    records=[{'period':'2022-12','value':12.2,'source_url':cbu.INFLATION_URL+'?lists_list_elements_983=page-3&mobile=Y'}]
    reviewed=cbu.review_inflation(records)
    assert reviewed[0]['value']==12.3
    assert reviewed[0]['original_value']==12.2
    assert reviewed[0]['source_url'].endswith('/Monetary_Policy_Report_4th_quarter.pdf')
    assert cbu.annual_inflation(reviewed)['2022']==12.3
    records[0]['value']=12.4 # A later source revision needs another review.
    assert cbu.review_inflation(records)[0]['value']==12.4


def test_initial_industry_table_has_one_explicit_dated_observation():
    fixture=json.loads((Path(__file__).parent/'fixtures/cbu_terminal_2020.json').read_text())['industry']
    result=cbu.parse_sector_rows(fixture['rows'],'industry',fixture['source_url'])
    assert result['date']=='2020-01-01'
    industry=next(r for r in result['rows'] if r['name']=='Промышленность')
    assert industry['observations']=={'2020-01-01':75636.369869}
    assert industry['share_pct']['2020-01-01']==pytest.approx(35.7482692511)


def test_sync_cannot_count_a_different_observation_month_as_loaded(monkeypatch):
    import requests,openpyxl
    from types import SimpleNamespace
    saved=[]
    def get(url,**kw):
        text='<a href="/detail">Информация об основных показателях коммерческих банков</a>' if 'bankstats' in url else '<a href="/table.xlsx">XLSX</a>'
        return SimpleNamespace(text=text,content=b'test',raise_for_status=lambda:None)
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr(openpyxl,'load_workbook',lambda *a,**k:SimpleNamespace(active=SimpleNamespace(values=[]),close=lambda:None))
    monkeypatch.setattr(cbu,'parse_bank_rows',lambda *a:{'date':'2024-12-01'})
    monkeypatch.setattr(cbu,'save',lambda *a:saved.append(a))
    result=cbu.sync_month(2025,1,with_sdmx=False)
    assert not saved
    assert 'main' not in result['loaded']


def test_published_nominative_month_name_is_a_valid_observation_date():
    fixture=json.loads((Path(__file__).parent/'fixtures/cbu_npl_202607.json').read_text())
    result=cbu.parse_bank_rows(fixture['rows'],'npl',fixture['source_url'])
    assert result['date']=='2026-07-01'
    assert result['sector']['npl_pct']==pytest.approx(3.569110665)


def test_discovery_prefers_observation_month_over_publication_order(monkeypatch):
    import requests,openpyxl
    from types import SimpleNamespace
    visited=[];saved=[]
    def get(url,**kw):
        visited.append(url)
        text='''<a href="/july">Сведения об основных показателях коммерческих банков 1 июля 2020</a>
        <a href="/june">Сведения об основных показателях коммерческих банков по состоянию на 1 июня 2020 года</a>''' if 'bankstats' in url else '<a href="/june.xlsx">XLSX</a>'
        return SimpleNamespace(text=text,content=b'test',raise_for_status=lambda:None)
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr(openpyxl,'load_workbook',lambda *a,**k:SimpleNamespace(active=SimpleNamespace(values=[]),close=lambda:None))
    monkeypatch.setattr(cbu,'parse_bank_rows',lambda *a:{'date':'2020-06-01'})
    monkeypatch.setattr(cbu,'save',lambda *a:saved.append(a))
    cbu.sync_month(2020,6,with_sdmx=False)
    assert 'https://cbu.uz/june' in visited
    assert 'https://cbu.uz/july' not in visited
    assert saved[0][1]=='2020-06-01'


def test_older_single_date_profitability_and_genitive_structure_headers():
    fixture=json.loads((Path(__file__).parent/'fixtures/cbu_terminal_2020.json').read_text())
    profit=fixture['profitability'];result=cbu.parse_sector_rows(profit['rows'],'profitability',profit['source_url'])
    assert result['date']=='2020-08-01'
    assert len(result['rows'][0]['observations'])==1
    source=fixture['structure_september'];result=cbu.parse_bank_rows(source['rows'],'structure',source['source_url'])
    sqbn=next(r for r in result['rows'] if r['ticker']=='SQBN')
    assert sqbn['household_loans_bn']==pytest.approx(4147.27033677697)


def test_targeted_history_retry_fetches_only_requested_source_kind(monkeypatch):
    import requests,openpyxl
    from types import SimpleNamespace
    fetched=[]
    def get(url,**kw):
        fetched.append(url)
        text='<a href="/npl">Информация о проблемных кредитах коммерческих банков</a>' if 'bankstats' in url else '<a href="/npl.xlsx">XLSX</a>'
        return SimpleNamespace(text=text,content=b'test',raise_for_status=lambda:None)
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr(openpyxl,'load_workbook',lambda *a,**k:SimpleNamespace(active=SimpleNamespace(values=[]),close=lambda:None))
    monkeypatch.setattr(cbu,'parse_bank_rows',lambda *a:{'date':'2026-09-01'})
    monkeypatch.setattr(cbu,'save',lambda *a:None)
    result=cbu.sync_month(2026,9,with_sdmx=False,kinds=['npl'])
    assert result=={'loaded':['npl'],'errors':[]}
    assert len(fetched)==3


def test_historical_negative_capital_is_kept_and_invalid_component_is_localised():
    fixture=json.loads((Path(__file__).parent/'fixtures/cbu_historical_variants.json').read_text())
    source=fixture['main_202112'];data=cbu.parse_bank_rows(source['rows'],'main',source['source_url'])
    row=next(r for r in data['rows'] if r['name']=='Апельсин банк')
    assert row['equity_bn']==pytest.approx(-.40328853)
    for key,name in [('structure_202102','Тибиси банк'),('structure_202306','Узум банк')]:
        source=fixture[key];data=cbu.parse_bank_rows(source['rows'],'structure',source['source_url'])
        row=next(r for r in data['rows'] if r['name']==name)
        assert row['company_loans_bn'] is None
        assert row['quality_issues'][0]['original_value']<0
        assert data['sector']['loans_bn']>0


def test_russian_cbu_page_with_uzbek_attachment_keeps_date_and_bank_identity():
    source=json.loads((Path(__file__).parent/'fixtures/cbu_historical_variants.json').read_text())['structure_202211']
    data=cbu.parse_bank_rows(source['rows'],'structure',source['source_url'])
    assert data['date']=='2022-11-01'
    sqbn=next(r for r in data['rows'] if r['ticker']=='SQBN')
    assert sqbn['loans_bn']==pytest.approx(47360.34525894)
    assert next(r for r in data['rows'] if r['ticker']=='HMKB')['household_loans_bn']>0


@pytest.mark.parametrize('page,kind,day,expected',[
    ('276492','main','2020-06-01',{'assets_bn':42448,'assets_share_pct':13.7}),
    ('134864','structure','2020-02-01',{'loans_bn':30604,'household_loans_bn':3300,'company_loans_bn':27304}),
])
def test_official_historical_html_preserves_spanned_columns_and_source(page,kind,day,expected):
    html=(Path(__file__).parent/f'fixtures/cbu_{page}.html').read_text()
    url=f'https://cbu.uz/ru/statistics/bankstats/{page}/'
    data=cbu.parse_bank_page(html,kind,url)
    assert data['date']==day and data['source_url']==url
    assert data['source_format']=='html'
    row=next(r for r in data['rows'] if r['ticker']=='SQBN')
    for field,value in expected.items():assert row[field]==value


def test_html_date_must_come_from_observation_and_agree_with_table():
    html=(Path(__file__).parent/'fixtures/cbu_276492.html').read_text()
    with pytest.raises(cbu.FormatChanged):
        cbu.parse_bank_page(html.replace('1 июня 2020','1 июля 2020',1),'main','https://cbu.uz/test')
    from bs4 import BeautifulSoup
    source=BeautifulSoup((Path(__file__).parent/'fixtures/cbu_134864.html').read_text(),'html.parser')
    source.h1.decompose()
    with pytest.raises(cbu.FormatChanged):
        cbu.parse_bank_page(str(source)+'<div class="main_date">1 февраля 2020</div>','structure','https://cbu.uz/test')


@pytest.mark.parametrize('page,kind,month,broken_attachment',[
    ('276492','main',6,True),('134864','structure',2,False),
])
def test_sync_recovers_official_html_when_attachment_is_wrong_or_absent(monkeypatch,page,kind,month,broken_attachment):
    import requests,openpyxl
    from types import SimpleNamespace
    html=(Path(__file__).parent/f'fixtures/cbu_{page}.html').read_text()
    if broken_attachment:html+='<a href="/wrong.xlsx">XLSX</a>'
    title={'main':'Сведения об основных показателях коммерческих банков','structure':'Сведения кредитах и депозитах коммерческих банков'}[kind]
    url=f'https://cbu.uz/ru/statistics/bankstats/{page}/';saved=[]
    def get(address,**kw):
        text=f'<a href="{url}">{title}</a>' if '?year=' in address else html
        return SimpleNamespace(text=text,content=b'wrong-table',raise_for_status=lambda:None)
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr(openpyxl,'load_workbook',lambda *a,**k:SimpleNamespace(active=SimpleNamespace(values=[['Wrong sector overview']]),close=lambda:None))
    monkeypatch.setattr(cbu,'save',lambda *a:saved.append(a))
    result=cbu.sync_month(2020,month,with_sdmx=False,kinds=[kind])
    assert result=={'loaded':[kind],'errors':[]}
    assert saved[0][1]==f'2020-{month:02d}-01'
    assert saved[0][2]['source_url']==url
    assert journal.events(event='load_format_changed')['total']==0


def test_html_percent_columns_are_points_even_without_cell_percent_sign():
    html=(Path(__file__).parent/'fixtures/cbu_276492.html').read_text().replace('13,7%','13,7')
    data=cbu.parse_bank_page(html,'main','https://cbu.uz/test')
    assert next(r for r in data['rows'] if r['ticker']=='SQBN')['assets_share_pct']==13.7


def test_invalid_html_spans_report_one_failure_and_preserve_last_good_data(monkeypatch):
    import requests
    from types import SimpleNamespace
    html=(Path(__file__).parent/'fixtures/cbu_134864.html').read_text().replace('rowspan="2"','rowspan="broken"',1)
    monkeypatch.setattr(requests,'get',lambda *a,**k:SimpleNamespace(text=html,raise_for_status=lambda:None))
    saved=[];monkeypatch.setattr(cbu,'save',lambda *a:saved.append(a))
    with pytest.raises(cbu.FormatChanged):
        cbu._read_month_table(html,'structure','https://cbu.uz/test','2020-02')
    assert not saved
    assert journal.events(event='load_format_changed')['total']==1
