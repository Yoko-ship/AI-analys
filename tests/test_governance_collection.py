"""Company-wide discovery must not depend on inclusion in the recent news feed."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import requests
from catalogue.storage import get_catalog_conn
from corporate_events import save_documents, from_fact

NOW = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    import securities_catalog
    import entity_resolver
    monkeypatch.setattr(securities_catalog, 'get_securities_map', lambda: {})
    monkeypatch.setattr(entity_resolver, 'resolve_by_index', lambda *a, **kw: None)
    monkeypatch.setattr(entity_resolver, 'get_org_index', lambda: {'by_name': {}})
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'governance.db'))
    conn = get_catalog_conn()
    with conn:
        conn.executemany('INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES (?,?,?)',
                         [('HMKB', 'Hamkorbank', '8'), ('HMKBP', 'Hamkorbank', '8'),
                          ('IPTB', 'Ipoteka-bank', '17'), ('NOID', 'Unmapped company', None)])
    conn.close()


def fixture(name):
    return json.loads(Path(f'tests/fixtures/openinfo/{name}.json').read_text(encoding='utf-8'))


def source_adapter(monkeypatch, *, fail=None, bad_issuer=False):
    from governance_collection import source
    data = [fixture(f'hmkb_2026_{kind}') for kind in ['supervisory', 'executive']]
    calls = []
    def get(url, *, params=None, timeout=None):
        calls.append((url, params))
        response = requests.Response()
        response.status_code = 200
        response.url = url
        if params:
            assert params['fact_number'] == 8 and params['organization_id'] in {'8', '17'}
            if fail == 'listing':
                response.status_code = 503
                response._content = b'{}'
                return response
            # One page each, including a real executive roster older than 120 days.
            page = params['page']
            record = data[page-1]
            raw = record['raw']
            payload = {'count': 2, 'results': [{'id': record['global_id'], 'object_id': raw['id'],
                       'organization': 9 if bad_issuer else 8, 'fact_number': 8, 'pub_date': raw['pub_date']}],
                       'next': 'http://new-api.openinfo.uz/api/v2/disclosure/facts/?page=2' if page == 1 else None}
            if params['organization_id'] == '17':
                payload = {'count': 0, 'results': [], 'next': None}
        else:
            if fail == 'detail':
                raise requests.Timeout('request timed out')
            raw = next(d['raw'] for d in data if str(d['global_id']) in url)
            payload = {'fact': [raw]}
        response._content = json.dumps(payload).encode()
        return response
    monkeypatch.setattr(source, 'get', get)
    return calls


def test_discovers_all_issuers_paginates_by_https_and_deduplicates_share_classes(catalog, monkeypatch):
    from governance_collection import run
    from server.company.shareholders import load
    calls = source_adapter(monkeypatch)
    result = run(now=NOW)
    assert result['attempted'] == 2
    assert result['imported'] == 2
    assert result['failed'] == 0
    assert result['missing_identity'] == ['NOID']
    assert [p['page'] for _,p in calls if p and p['organization_id'] == '8'] == [1, 2]
    assert all(url.startswith('https://new-api.openinfo.uz/') for url,_ in calls)
    assert load('HMKB')['management']['items'] == load('HMKBP')['management']['items']
    assert load('IPTB')['management']['collection']['reason'] == 'NO_FORM8_DISCLOSURES'
    assert load('NOID')['management']['collection']['reason'] == 'MISSING_ISSUER_ID'
    before = len(calls)
    assert run(now=NOW)['attempted'] == 0
    assert len(calls) == before


def test_market_directory_share_classes_and_issuers_without_financial_catalog_are_included(catalog, monkeypatch):
    import securities_catalog
    import entity_resolver
    from governance_collection import run
    from server.company.shareholders import load
    with get_catalog_conn() as conn:
        conn.execute("DELETE FROM catalog_companies WHERE ticker IN ('HMKBP','IPTB')")
    source_adapter(monkeypatch)
    assert run(now=NOW)['attempted'] == 1
    monkeypatch.setattr(securities_catalog, 'get_securities_map', lambda: {'HMKB': {'name': 'Hamkorbank'}, 'HMKBP': {'name': 'Hamkorbank'}, 'IPTB': {}})
    monkeypatch.setattr(entity_resolver, 'resolve_by_index', lambda ticker, isin=None: {'org_id': '17'} if ticker == 'IPTB' else None)
    # A new share class must become eligible even if its issuer was checked today.
    result = run(now=NOW)
    assert result['attempted'] == 2
    assert load('HMKBP')['management']['items'] == load('HMKB')['management']['items']
    assert load('HMKBP')['management']['collection']['issuer_id'] == '8'
    assert load('IPTB')['management']['collection']['reason'] == 'NO_FORM8_DISCLOSURES'


def test_failed_source_preserves_previous_people_and_records_exact_stage(catalog, monkeypatch):
    from governance_collection import run
    from server.company.shareholders import load
    save_documents([from_fact(fixture('hmkb_2026_executive')['raw'])])
    source_adapter(monkeypatch, fail='listing')
    result = run(ticker='HMKB', now=NOW)
    assert result['failed'] == 1
    management = load('HMKB')['management']
    assert management['items']
    assert management['collection']['reason'] == 'HTTP_503'
    assert management['collection']['stage'] == 'listing'
    assert management['collection']['checked_at'].startswith('2026-11-08')


def test_market_only_company_uses_exact_registered_name_without_fuzzy_matching(catalog, monkeypatch):
    import entity_resolver
    import securities_catalog
    from governance_collection import _issuers
    name = '"Transgazmaxsusqurilish" aksiyadorlik jamiyati'
    monkeypatch.setattr(securities_catalog, 'get_securities_map', lambda: {'TGMQ': {'name': name}, 'SIMILAR': {'name': 'Transgazmaxsus'}})
    monkeypatch.setattr(entity_resolver, 'get_org_index', lambda: {'by_name': {
        entity_resolver._normalize_name_key(name): {'org_id': '737', 'name': name}}})
    assert _issuers('TGMQ') == ({'737': ['TGMQ']}, [])
    assert _issuers('SIMILAR') == ({}, ['SIMILAR'])


def test_ambiguous_company_names_cannot_attach_an_unknown_share_class(catalog, monkeypatch):
    import securities_catalog
    from governance_collection import _issuers
    monkeypatch.setattr(securities_catalog, 'get_securities_map', lambda: {t: {'name': 'Same name'} for t in ('HMKB','IPTB','NEWP')})
    assert _issuers('NEWP') == ({}, ['NEWP'])


@pytest.mark.parametrize('failure,reason', [('detail', 'TIMEOUT'), ('identity', 'ISSUER_MISMATCH')])
def test_bad_source_never_becomes_no_data(catalog, monkeypatch, failure, reason):
    from governance_collection import run
    calls = source_adapter(monkeypatch, fail=failure, bad_issuer=failure == 'identity')
    result = run(ticker='HMKB', now=NOW)
    assert result['failed'] == 1
    assert result['companies'][0]['reason'] == reason
    if failure == 'identity':
        assert len(calls) == 1


def test_bounded_discovery_resumes_cached_archive_and_manual_force_bypasses_schedule(catalog, monkeypatch):
    from governance_collection import run
    calls = source_adapter(monkeypatch)
    first = run(ticker='HMKB', now=NOW, max_documents=1)
    assert first['companies'][0]['reason'] == 'ARCHIVE_LIMIT_REACHED'
    assert first['imported'] == 1
    second = run(ticker='HMKB', now=NOW, max_documents=1, force=True)
    assert second['companies'][0]['state'] == 'complete'
    assert second['imported'] == 1
    assert sum('/99726/' in url for url,_ in calls) == 1
    assert run(ticker='HMKB', now=NOW+timedelta(days=1), force=True)['attempted'] == 1


def test_discovery_does_not_follow_arbitrary_next_urls(catalog, monkeypatch):
    from governance_collection import source, run
    calls = source_adapter(monkeypatch)
    original = source.get
    def tampered(url, **kw):
        response = original(url, **kw)
        if (kw.get('params') or {}).get('page') == 1:
            payload = response.json()
            payload['next'] = 'http://127.0.0.1/private'
            response._content = json.dumps(payload).encode()
        return response
    monkeypatch.setattr(source, 'get', tampered)
    assert run(ticker='HMKB', now=NOW)['imported'] == 2
    assert all('127.0.0.1' not in url for url,_ in calls)


def test_vacancy_only_roster_is_not_a_complete_executive_roster():
    from governance_collection import _complete_executive
    raw = fixture('iptb_2026_governance')['raw']
    raw['factsmembershipexecutive'] = [dict(raw['factsmembershipexecutive'][0], name='Вакансия')]
    assert not _complete_executive(from_fact(raw), '2026-11-08')
