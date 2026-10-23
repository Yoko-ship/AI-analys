"""The 65-issuer screener must not rebuild the security registry per alias."""
import asyncio
from concurrent.futures import ThreadPoolExecutor


def test_issuer_alias_lookup_reuses_registry_only_inside_one_read_batch(monkeypatch):
    from catalogue import read_batch, filings
    import securities_catalog
    calls=[]
    monkeypatch.setattr(securities_catalog,'get_securities_map',lambda: calls.append(1) or {'HMKB':{'isin':'UZ7024720009'},'HMKBP':{'isin':'UZ702472K015'}})
    monkeypatch.setattr(filings,'_registered_org',lambda c,t:'7' if t=='HMKB' else '')
    with read_batch.scope():
        assert filings._issuer_org(None,'HMKBP')=='7'
        assert filings._issuer_org(None,'HMKBP')=='7'
    assert len(calls)==1
    with read_batch.scope():assert filings._issuer_org(None,'HMKBP')=='7'
    assert len(calls)==2


def test_batch_reads_share_work_across_threads_and_never_cache_across_requests():
    from catalogue import read_batch
    calls=[]
    async def request():
        with read_batch.scope():
            return await asyncio.gather(*(asyncio.to_thread(read_batch.get,'test',lambda: calls.append(1) or len(calls)) for _ in range(20)))
    assert asyncio.run(request())==[1]*20
    assert asyncio.run(request())==[2]*20


def test_corrections_are_loaded_once_per_issuer_and_refreshed_next_request(monkeypatch):
    from catalogue import read_batch
    import data_quality
    calls=[]
    monkeypatch.setattr(data_quality,'approved_corrections_series',lambda ticker,form:calls.append(ticker) or {(2020,0):{'total_equity':559_840_271}},raising=False)
    with read_batch.scope():
        assert data_quality.approved_corrections_for('KVTS','NSBU',2020,0)=={'total_equity':559_840_271}
        assert data_quality.approved_corrections_for('KVTS','NSBU',2021,0)=={}
    assert calls==['KVTS']
    with read_batch.scope():data_quality.approved_corrections_for('KVTS','NSBU',2020,0)
    assert calls==['KVTS','KVTS']


def test_screener_serializes_issuer_reads_to_avoid_sqlite_contention(monkeypatch):
    from server.terminal import service
    active=0
    peak=0
    async def series(*args):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        await asyncio.sleep(.001)
        active-=1
        return {'periods':[]}
    companies=[{'ticker':f'T{i}','kind':'industry'} for i in range(12)]
    monkeypatch.setattr(service,'universe',lambda:companies)
    monkeypatch.setattr(service,'market_context',lambda:{})
    monkeypatch.setattr(service.cbu,'context',lambda:{'banks':{}})
    monkeypatch.setattr(service,'financial_series',series)
    monkeypatch.setattr(service.dividends,'read_snapshot',lambda ticker:[])
    result=asyncio.run(service.screener())
    assert len(result['rows'])==12
    assert peak==1


def test_simultaneous_screeners_share_only_inflight_work_and_isolate_results(monkeypatch):
    from server.terminal import service
    calls=[]
    async def build(form,scope,year):
        calls.append((form,scope,year));await asyncio.sleep(.01)
        return {'rows':[{'value':len(calls)}]}
    monkeypatch.setattr(service,'_screener',build)
    async def scenario():
        a,b=await asyncio.gather(service.screener(),service.screener())
        assert len(calls)==1
        a['rows'][0]['value']=99
        assert b['rows'][0]['value']==1
        assert (await service.screener())['rows'][0]['value']==2
    asyncio.run(scenario())


def test_distinct_screener_contexts_do_not_contend_for_sqlite(monkeypatch):
    from server.terminal import service
    active=peak=0
    async def build(form,scope,year):
        nonlocal active,peak
        active+=1;peak=max(peak,active);await asyncio.sleep(.01);active-=1
        return {'context':[form,scope,year]}
    monkeypatch.setattr(service,'_screener',build)
    async def scenario():
        return await asyncio.gather(service.screener(),service.screener('MSFO','consolidated'),service.screener(year='2024'))
    results=asyncio.run(scenario())
    assert peak==1
    assert [r['context'] for r in results]==[['NSBU','separate',None],['MSFO','consolidated',None],['NSBU','separate','2024']]


def test_cancelled_screener_waiter_does_not_cancel_shared_build(monkeypatch):
    from server.terminal import service
    calls=[]
    async def scenario():
        started=asyncio.Event();finish=asyncio.Event()
        async def build(*args):
            calls.append(1);started.set();await finish.wait();return {'ok':True}
        monkeypatch.setattr(service,'_screener',build)
        first=asyncio.create_task(service.screener());await started.wait()
        second=asyncio.create_task(service.screener());await asyncio.sleep(0)
        first.cancel()
        try:await first
        except asyncio.CancelledError:pass
        finish.set();assert await second=={'ok':True}
        assert len(calls)==1
    asyncio.run(scenario())


def test_failed_screener_build_is_retried_and_never_cached(monkeypatch):
    from server.terminal import service
    calls=[]
    async def build(*args):
        calls.append(1)
        if len(calls)==1:raise ValueError('source unavailable')
        return {'ok':True}
    monkeypatch.setattr(service,'_screener',build)
    async def scenario():
        import pytest
        with pytest.raises(ValueError):await service.screener()
        assert await service.screener()=={'ok':True}
    asyncio.run(scenario())
    assert len(calls)==2
