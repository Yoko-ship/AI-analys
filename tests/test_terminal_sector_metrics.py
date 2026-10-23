import json
from pathlib import Path
import pytest
from financial_analysis import sector_calculations as calculations

INS = json.loads((Path(__file__).parent/'fixtures/terminal_insurers_mockup.json').read_text())['insurers']


@pytest.mark.parametrize('ticker,retention,loss,expense,combined,investment',[
    ('TMYS',94.9,79.2,19.3,98.6,25.5),('KFSK',35.4,81.7,18.5,100.2,11.6),
    ('KASU',98.3,33.7,69.4,103.2,1.3),('UZAS',93.2,45.5,61.7,107.2,7.8),('ALSM',99.2,91.4,16.4,107.8,2.4)])
def test_five_insurer_half_years_match_the_tz(ticker,retention,loss,expense,combined,investment):
    f=INS[ticker]['f']; current={k:v[0] for k,v in f.items()}; previous={k:v[1] for k,v in f.items()}
    rows={r['metric']:r for r in calculations.financial_ratios(current,previous,previous,'insurance','nsbu','2026Q2')}
    for key,expected in [('retention',retention),('loss_ratio',loss),('expense_ratio',expense),('combined_ratio',combined),('investment_to_premiums',investment)]:
        assert rows[key]['value']==pytest.approx(expected,abs=.06)
        assert rows[key]['name_ru']!=key


def test_insurance_missing_or_nonpositive_premiums_do_not_make_a_ratio():
    current={'insurance_service_cost':10,'expenses':20,'revenue':0,'insurance_premiums':None,'ceded_premiums':0}
    rows={r['metric']:r for r in calculations.financial_ratios(current,{}, {},'insurance','nsbu','2026Q2')}
    assert rows['retention']['value'] is None
    assert rows['combined_ratio']['value'] is None


def test_bank_nim_and_cost_of_risk_are_annualised_with_average_balances():
    current={'net_interest_income_before_provisions':50,'total_assets':1000,'loan_portfolio':600,'credit_loss_provisions':6}
    rows={r['metric']:r for r in calculations.financial_ratios(current,{}, {'total_assets':800,'loan_portfolio':400},'bank','nsbu','2026Q2')}
    assert rows['nim']['value']==pytest.approx(50*2/900*100)
    assert rows['cost_of_risk']['value']==pytest.approx(6*2/500*100)


def test_all_enterprise_ratios_supply_names_from_the_api():
    for row in calculations.enterprise_ratios({},'non_financial','nsbu','2026Q2'):
        assert row['name_ru'] and row['name_ru']!=row['metric']
