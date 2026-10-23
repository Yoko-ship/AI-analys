import pytest
from admin_control import rules, store
from financial_analysis import sector_calculations as calc


def test_financial_formula_draft_changes_only_its_named_metric():
    config={'code':'combined_ratio','numerators':['expenses'],'denominators':['revenue'],'unit':'percent','basis':'previous',
            'test_cases':[{'values':{'insurance_service_cost':45,'expenses':20,'revenue':100},'organization_type':'insurance','expected':20},
                          {'values':{'expenses':20,'revenue':0},'organization_type':'insurance','expected':None}]}
    rule={'id':'financial-draft','category':'financial_formula','config':config}
    rules.validate('financial_formula',config)
    assert rules.test_rule(rule)['passed']
    snapshot=rules.apply_snapshot({'organization_type':'insurance','current_values':config['test_cases'][0]['values']},{},rules=[rule])
    rows={r['metric']:r for r in calc.financial_ratios(config['test_cases'][0]['values'],{}, {},'insurance','nsbu','2026Q2',methods=snapshot['financial_formula_methods'])}
    assert rows['combined_ratio']['value']==20
    assert rows['loss_ratio']['value']==45
    assert snapshot['formula_rule_versions']['combined_ratio']=='financial-draft'
    with pytest.raises(store.ControlError):rules.validate('financial_formula',{**config,'numerators':['arbitrary_expression()']})
