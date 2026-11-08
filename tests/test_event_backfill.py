from datetime import datetime, timezone, timedelta
import pytest


@pytest.mark.parametrize('failed', [0, 1])
def test_daily_entrypoint_discovers_governance_for_all_issuers(monkeypatch, capsys, failed):
    import corporate_event_backfill as backfill
    import governance_collection
    calls = []
    monkeypatch.setattr(backfill, 'run', lambda **kw: {'failed': 0, 'enriched': 3})
    def collect(**kw):
        calls.append(kw)
        kw['progress']({'tickers': ['HMKB', 'HMKBP'], 'imported': 2, 'state': 'failed' if failed else 'complete',
                        'stage': 'detail', 'reason': 'HTTP_503' if failed else 'EXECUTIVE_ROSTER_FOUND'})
        return {'attempted': 71, 'failed': failed}
    monkeypatch.setattr(governance_collection, 'run', collect)
    assert backfill.main(['--limit', '40', '--days', '120']) == failed
    assert len(calls) == 1 and calls[0]['limit'] == 100
    from collection_ops.model import parse_receipts
    output = capsys.readouterr().out
    assert 'governance' in output
    receipts = parse_receipts(output.splitlines())
    assert receipts[0]['counts']['written'] == 2
    if failed:
        assert receipts[-1]['ok'] is False and receipts[-1]['reason'] == 'HTTP_503'
        assert 'detail' in receipts[-1]['stage']


def test_historical_enrichment_is_bounded_and_does_not_retry_every_page_load(monkeypatch,tmp_path):
    import corporate_event_backfill as backfill
    import corporate_events as ce
    import catalogue.storage as cs
    monkeypatch.setattr(cs,'_catalog_db_path',lambda:str(tmp_path/'events.db'))
    docs=[{'source_url':f'https://openinfo.uz/ru/announce/{i}','confidence':'review'} for i in range(5)]
    monkeypatch.setattr(ce,'feed',lambda *a,**k:{'items':[{'documents':docs}]})
    calls=[]
    def refresh(source):
        calls.append(source)
        if source.endswith('/0'):raise RuntimeError('Source down')
        return {'confidence':'confirmed'}
    monkeypatch.setattr(ce,'refresh_document',refresh)
    now=datetime(2026,10,26,tzinfo=timezone.utc)
    first=backfill.run(limit=2,now=now)
    assert first['attempted']==2 and first['failed']==1
    backfill.run(limit=2,now=now)
    assert len(set(calls))==4
    backfill.run(limit=2,now=now)
    assert len(calls)==5
    assert backfill.run(limit=2,now=now)['attempted']==0
    assert backfill.run(limit=2,now=now+timedelta(days=8))['attempted']==2


def test_rechecks_visit_oldest_evidence_before_recently_checked_documents(monkeypatch,tmp_path):
    import corporate_event_backfill as backfill
    import corporate_events as ce
    import catalogue.storage as cs
    monkeypatch.setattr(cs,'_catalog_db_path',lambda:str(tmp_path/'events.db'))
    sources=[f'https://openinfo.uz/ru/announce/{i}' for i in range(3)]
    monkeypatch.setattr(ce,'feed',lambda *a:{'items':[{'documents':[{'source_url':s} for s in sources]}]})
    calls=[]
    monkeypatch.setattr(ce,'refresh_document',lambda source:calls.append(source))
    now=datetime(2026,10,26,tzinfo=timezone.utc)
    backfill.run(limit=1,now=now)
    backfill.run(limit=2,now=now+timedelta(days=8))
    # New evidence takes precedence over an already checked recent story.
    assert calls==sources
    backfill.run(limit=1,now=now+timedelta(days=16))
    assert calls[-1]==sources[0]


def test_new_extractor_version_rechecks_recent_sources_once_including_failures(monkeypatch,tmp_path):
    import corporate_event_backfill as backfill
    import corporate_event_fields as fields
    import corporate_events as ce
    import catalogue.storage as cs
    monkeypatch.setattr(cs,'_catalog_db_path',lambda:str(tmp_path/'events.db'))
    source='https://openinfo.uz/ru/facts/16/84524'
    monkeypatch.setattr(ce,'feed',lambda *a:{'items':[{'documents':[{'source_url':source}]}]})
    calls=[]
    def refresh(url):
        calls.append(url)
        raise RuntimeError('temporarily unavailable')
    monkeypatch.setattr(ce,'refresh_document',refresh)
    now=datetime(2026,10,26,tzinfo=timezone.utc)
    backfill.run(limit=1,now=now)
    monkeypatch.setattr(fields,'VERSION',fields.VERSION+1)
    assert backfill.run(limit=1,now=now)['attempted']==1
    assert backfill.run(limit=1,now=now)['attempted']==0
    assert len(calls)==2
