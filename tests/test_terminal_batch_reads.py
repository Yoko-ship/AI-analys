"""The 65-issuer screener must not rebuild the security registry per alias."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pytest


@pytest.mark.parametrize('ticker,kind,year,form,scope', [
    ('BIOK', 'industry', None, 'NSBU', 'separate'),
    ('HMKB', 'bank', 2024, 'NSBU', 'separate'),
    ('BIOK', 'industry', 2025, 'MSFO', 'consolidated'),
])
def test_peer_screen_reads_only_comparable_issuer_types_without_changing_values(monkeypatch, ticker, kind, year, form, scope):
    from server.terminal import service, valuation
    companies = [{'ticker': t, 'kind': k} for t, k in [
        ('BIOK', 'industry'), ('BECM', 'industry'), ('QZSM', 'industry'), ('UZTL', 'industry'),
        ('HMKB', 'bank'), ('AGBA', 'bank'), ('ALSK', 'insurance'), ('UZAL', 'financial')]]
    reads, macro_reads = [], []
    monkeypatch.setattr(service, 'universe', lambda: companies)
    monkeypatch.setattr(service, 'market_context', lambda: {
        c['ticker']: {'price': 14_400, 'market_cap': 120_000, 'market_date': '2026-11-06'} for c in companies})
    def central(year=None):
        macro_reads.append(year)
        return {'banks': {'HMKB': {'npl': {'npl_pct': 1.7}}}, 'sector_series': {'capital': {'period': str(year)}}}
    monkeypatch.setattr(service.cbu, 'context', central)
    monkeypatch.setattr(service.bank_ratios, 'enrich', lambda ticker, row, *args: row)
    monkeypatch.setattr(service.dividends, 'read_snapshot', lambda ticker: [])
    async def financials(ticker, frequency, standard, perimeter):
        reads.append(ticker)
        return {'standard': standard, 'scope': perimeter, 'periods': ['2024', '2025'],
                'series': {field: {'values': {'2024': value, '2025': value * 1.2}}
                           for field, value in [('net_profit', 1000), ('total_assets', 10000),
                                                ('total_equity', 5000), ('net_revenue', 15000)]}}
    monkeypatch.setattr(service, 'financial_series', financials)
    full = asyncio.run(service.screener(form, scope, year))
    reads.clear(); macro_reads.clear()
    selected = asyncio.run(service.screener(form, scope, year, peer_ticker=ticker.lower()))
    expected = [row for row in full['rows'] if row['kind'] == kind]
    assert selected['rows'] == expected
    assert reads == [c['ticker'] for c in companies if c['kind'] == kind]
    assert macro_reads == ([year] if kind == 'bank' else [])
    base = next(row for row in selected['rows'] if row['ticker'] == ticker)
    assert valuation.calculate(base, selected['rows'], valuation.REFERENCE) == valuation.calculate(base, full['rows'], valuation.REFERENCE)


def test_missing_peer_issuer_does_not_fall_back_to_loading_the_whole_market(monkeypatch):
    from server.terminal import service
    monkeypatch.setattr(service, 'universe', lambda: [{'ticker': 'HMKB', 'kind': 'bank'}])
    def unused(*args, **kwargs):
        pytest.fail('An unavailable peer issuer must not trigger market or financial reads')
    monkeypatch.setattr(service, 'market_context', unused)
    monkeypatch.setattr(service, 'financial_series', unused)
    monkeypatch.setattr(service.cbu, 'context', unused)
    assert asyncio.run(service.screener(peer_ticker='BIOK'))['rows'] == []


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
