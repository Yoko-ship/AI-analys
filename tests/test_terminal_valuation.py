import pytest
from fastapi.testclient import TestClient
import api


@pytest.fixture
def mockup_banks():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).parent / 'fixtures/terminal_valuation_mockup_20261015.json').read_text())['rows']


def test_hmkb_dashboard_compares_all_models_in_uzs_per_share(mockup_banks):
    from statistics import median
    from server.terminal.valuation import calculate, REFERENCE
    base = next(row for row in mockup_banks if row['ticker'] == 'HMKB')
    result = calculate(base, mockup_banks, REFERENCE)
    pb = result['models']['justified_pb']
    assert pb['per_share']['value'] == pytest.approx((25.429424127400697 - 9.8) / (19.83 - 9.8) * 97.44 / 1.8874894128812407)
    estimates = []
    for code in ('peers_pb', 'peers_pe', 'justified_pb'):
        model = result['models'][code]
        assert model['per_share']['unit'] == 'UZS/share'
        estimates.append(model['per_share']['value'])
    assert result['summary']['value'] == pytest.approx(median(estimates))
    assert result['summary']['low'] == min(estimates)
    assert result['summary']['high'] == max(estimates)
    assert result['summary']['price_to_value_pct'] == pytest.approx(base['price'] / median(estimates) * 100)
    assert result['current_price'] == 97.44


def test_mockup_profitability_rule_rejects_agba_pb_but_keeps_hmkb(mockup_banks):
    from server.terminal.valuation import calculate, REFERENCE
    results = {ticker: calculate(next(r for r in mockup_banks if r['ticker'] == ticker), mockup_banks, REFERENCE) for ticker in ('AGBA', 'HMKB')}
    assert results['AGBA']['models']['peers_pb']['reason'] == 'ROE_BELOW_PEERS'
    assert results['HMKB']['models']['peers_pb']['reason'] is None
    # A loss/low return doesn't prevent a separately applicable method.
    only = results['AGBA']['models']['peers_pe']['per_share']
    assert results['AGBA']['summary']['low'] == only['low']
    assert results['AGBA']['summary']['high'] == only['high']


@pytest.mark.parametrize('price,cap', [(None, 100), (0, 100), (12, None), (12, 0)])
def test_missing_market_basis_does_not_mislabel_issuer_value_as_share_price(price, cap):
    from server.terminal.valuation import calculate, REFERENCE
    base = {'ticker': 'TEST', 'kind': 'bank', 'roe': 20, 'equity': 100, 'net_profit': 20, 'price': price, 'market_cap': cap}
    rows = [{**base, 'ticker': str(i), 'pb': i + 1, 'pe': 5 + i} for i in range(3)]
    result = calculate(base, rows, REFERENCE)
    assert result['models']['peers_pb']['per_share']['reason'] == 'MARKET_BASIS_UNAVAILABLE'
    assert result['summary']['value'] is None
    assert result['summary']['price_to_value_pct'] is None


def test_single_dividend_method_retains_sensitivity_and_missing_price():
    from server.terminal.valuation import calculate, REFERENCE
    result = calculate({'dividend': {'decision': {'ordinary_amount': 1}}}, [], REFERENCE)
    model = result['models']['gordon']['per_share']
    assert result['summary']['value'] == model['value']
    assert result['summary']['low'] == model['low']
    assert result['summary']['high'] == model['high']
    assert result['summary']['price_to_value_pct'] is None


def test_quarantined_peers_cannot_enter_model_even_with_cached_positive_ratios():
    from server.terminal.valuation import calculate, REFERENCE
    base = {'ticker': 'TEST', 'kind': 'bank', 'period': '2025', 'roe': 20, 'equity': 100, 'net_profit': 20, 'price': 12, 'market_cap': 120}
    rows = [{**base, 'ticker': str(i), 'pb': i+1, 'pe': i+5} for i in range(3)]
    rows[0]['issues'] = [{'code': 'VALUE_QUARANTINE', 'period': '2025'}]
    result = calculate(base, rows, REFERENCE)
    assert result['models']['peers_pb']['reason'] == 'INSUFFICIENT_PEERS'
    # The same source guard applies to the issuer being valued.
    result = calculate({**base, 'issues': rows[0]['issues']}, rows, REFERENCE)
    assert result['summary']['value'] is None
    assert result['models']['justified_pb']['per_share']['reason'] == 'SOURCE_QUALITY'


def test_models_require_comparable_positive_inputs_and_explicit_parameters():
    from server.terminal.valuation import calculate
    base={'ticker':'AGBA','kind':'bank','period':'2025','standard':'NSBU','scope':'separate','roe':20,'equity':100,'net_profit':20,'market_cap':120,'price':12,'dividend':{'decision':{'ordinary_amount':1}}}
    peers=[{**base,'ticker':t,'pb':pb,'pe':pe} for t,pb,pe in [('HMKB',1,5),('IPKY',2,10),('SQBN',3,15)]]
    params={'key_rate':14,'default_spread':3.06,'equity_premium':8.89,'growth':9.8}
    result=calculate(base,peers,params)
    assert result['required_return']==pytest.approx(19.83)
    assert result['models']['justified_pb']['value']==pytest.approx((20-9.8)/(19.83-9.8))
    assert result['models']['peers_pb']['low']==150
    assert result['models']['gordon']['value']==pytest.approx(1*1.098/.1003)
    assert calculate({**base,'roe':5},peers,params)['models']['justified_pb']['reason']=='ROE_BELOW_GROWTH'
    assert calculate(base,[],params)['models']['peers_pb']['reason']=='INSUFFICIENT_PEERS'
    assert calculate(base,peers,{**params,'growth':20})['models']['gordon']['reason']=='RETURN_NOT_ABOVE_GROWTH'


def test_fv_endpoint_never_exposes_unvalidated_models_publicly():
    assert TestClient(api.app).get('/api/admin/terminal/valuation/AGBA').status_code==401


def test_screener_valuation_matches_fv_and_keeps_the_admin_boundary(monkeypatch, mockup_banks):
    from server.terminal import service, configuration, valuation
    from server.auth import access
    client = TestClient(api.app)
    assert client.get('/api/admin/terminal/valuations').status_code == 401
    calls = []
    async def screener(form, scope):
        calls.append((form, scope))
        return {'rows': mockup_banks}
    monkeypatch.setattr(service, 'screener', screener)
    monkeypatch.setattr(configuration, 'parameters', lambda: {'values': valuation.REFERENCE, 'as_of': '2026-10-15', 'version': 'test'})
    api.app.dependency_overrides[access._admin_panel_gate] = lambda: {'id': 1, 'is_admin': True}
    try:
        response = client.get('/api/admin/terminal/valuations?form=NSBU&scope=consolidated')
        assert response.status_code == 200
        rows = {row['ticker']: row for row in response.json()['rows']}
        single = client.get('/api/admin/terminal/valuation/HMKB').json()
        assert rows['HMKB']['price_to_value_pct'] == single['summary']['price_to_value_pct']
        assert rows['HMKB']['period'] == '2025'
        assert rows['HMKB']['standard'] == 'NSBU'
        assert all(call == ('NSBU', 'separate') for call in calls)
    finally:
        api.app.dependency_overrides.pop(access._admin_panel_gate, None)


def test_valuation_assumptions_use_existing_versioned_rule_workflow():
    from admin_control import rules
    from server.terminal import valuation
    config={'code':'terminal_fv','as_of':'2026-10-15',**valuation.REFERENCE,'test_cases':[{'base':{'kind':'bank','roe':20},'peers':[], 'expected':{'required_return':19.83}}]}
    rules.validate('valuation',config)
    assert rules.test_rule({'category':'valuation','config':config})['passed']
    with pytest.raises(Exception):rules.validate('valuation',{**config,'key_rate':float('nan')})
