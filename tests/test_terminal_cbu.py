import json
from pathlib import Path
import pytest
from server.terminal import cbu
from server.terminal import journal

FIXTURE=json.loads((Path(__file__).parent/'fixtures/cbu_terminal_202609.json').read_text())


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
