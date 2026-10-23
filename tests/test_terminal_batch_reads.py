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
