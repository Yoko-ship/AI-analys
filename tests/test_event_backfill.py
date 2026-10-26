from datetime import datetime, timezone, timedelta


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
