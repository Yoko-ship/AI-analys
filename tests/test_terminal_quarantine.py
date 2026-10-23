import pytest
from server.terminal import journal


def data(rows):
    return {'ok':True,'ticker':'KVTS','standard':'NSBU','freq':'annual','periods':sorted(rows),
            'series':{f:{'money':True,'unit':'UZS','values':{p:r[f] for p,r in rows.items() if f in r}} for f in {k for r in rows.values() for k in r}}}


def test_kvts_glued_cell_and_odmp_unit_error_are_hidden_but_original_is_retained(monkeypatch):
    from server.terminal.quarantine import protect
    monkeypatch.setattr('server.terminal.quarantine.reviewed',lambda *a:False)
    original=data({'2019':{'total_liabilities':126803839000},'2020':{'total_assets':914358452000,'total_liabilities':1.268038405598403e20,'total_equity':-1.2680383964548186e20},'2021':{'total_liabilities':648930509000}})
    safe=protect(original,'KVTS','NSBU')
    assert safe['series']['total_equity']['values'].get('2020') is None
    assert safe['series']['total_liabilities']['values'].get('2020') is None
    assert original['series']['total_equity']['values']['2020']< -1e20
    assert any(g['code']=='VALUE_QUARANTINE' for g in safe['data_gaps'])
    odmp=data({'2020':{'total_assets':7358369000,'net_profit':888295147190}})
    assert protect(odmp,'ODMP','NSBU')['series']['net_profit']['values'].get('2020') is None
    protect(original,'KVTS','NSBU')
    assert journal.events(event='value_quarantine')['total']==3


def test_real_flow_extremes_are_not_subject_to_balance_jump_rule(monkeypatch):
    from server.terminal.quarantine import protect
    monkeypatch.setattr('server.terminal.quarantine.reviewed',lambda *a:False)
    # The audit found these losses faithful to the filings, not scale errors.
    raw=data({'2023':{'net_profit':1e9},'2024':{'net_profit':-1.7e12,'total_assets':3e13},'2025':{'net_profit':2e9}})
    assert protect(raw,'MCBA','NSBU')['series']['net_profit']['values']['2024']==-1.7e12


def test_review_is_bound_to_exact_value_and_asset_context():
    from server.terminal.quarantine import reviewed
    assert reviewed('UZNF','NSBU','2025Q1','net_profit',-19091000,10000000)
    assert not reviewed('UZNF','NSBU','2025Q1','net_profit',-19091000000,10000000)
    assert not reviewed('UZNF','NSBU','2025Q1','net_profit',-19091000,100000)


def test_no_ratio_survives_a_quarantined_input(monkeypatch):
    from server.terminal.quarantine import protect
    monkeypatch.setattr('server.terminal.quarantine.reviewed',lambda *a:False)
    raw=data({'2020':{'total_assets':7358369000,'net_profit':888295147190,'roe':9000}})
    raw['series']['roe']['money']=False
    safe=protect(raw,'ODMP','NSBU')
    assert safe['series']['roe']['values'].get('2020') is None
