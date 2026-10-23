import pytest
from fastapi.testclient import TestClient
import api


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


def test_valuation_assumptions_use_existing_versioned_rule_workflow():
    from admin_control import rules
    from server.terminal import valuation
    config={'code':'terminal_fv','as_of':'2026-10-15',**valuation.REFERENCE,'test_cases':[{'base':{'kind':'bank','roe':20},'peers':[], 'expected':{'required_return':19.83}}]}
    rules.validate('valuation',config)
    assert rules.test_rule({'category':'valuation','config':config})['passed']
    with pytest.raises(Exception):rules.validate('valuation',{**config,'key_rate':float('nan')})
