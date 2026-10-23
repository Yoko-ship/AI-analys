import json
from pathlib import Path
from server.terminal import journal


def test_replayed_publication_does_not_inflate_daily_counts(monkeypatch):
    from reporting import publication
    monkeypatch.setattr(publication.store,'record_report',lambda r:r)
    monkeypatch.setattr(publication.store,'publication_version',lambda r:r['version'])
    monkeypatch.setattr(publication,'record_analysis',lambda *a,**kw:None)
    report={'issuer':{'ticker':'SQBN'},'version':'v1','source_snapshot_hash':'source1','period':'2025','standard':'nsbu','status':'available','verdict':{'status':'positive'},'risks':[]}
    publication.publish_report(report);publication.publish_report(report)
    assert journal.events(event='ai_published')['total']==1


def test_five_real_insurers_trigger_retention_check_but_stable_cession_does_not():
    from server.terminal.quality import insurance_checks
    data=json.loads((Path(__file__).parent/'fixtures/terminal_insurers_mockup.json').read_text())['insurers']
    for ticker,row in data.items():
        current={k:v[0] for k,v in row['f'].items()};previous={k:v[1] for k,v in row['f'].items()}
        assert 'ins_retention_jump' in {r['event'] for r in insurance_checks(current,previous,{},{})},ticker
    assert not insurance_checks({'insurance_premiums':100,'ceded_premiums':10},{'insurance_premiums':100,'ceded_premiums':10},{},{})


def test_reserve_check_compares_annual_close_to_quarter_opening_not_current_balance():
    from server.terminal.quality import insurance_checks
    missing=insurance_checks({}, {}, {'total_assets':642e9},{'total_assets':383e9})
    assert missing[0]['event']=='ins_reserves_missing'
    assert not insurance_checks({'total_assets':900e9}, {}, {'total_assets':642e9},{'total_assets':642e9})
