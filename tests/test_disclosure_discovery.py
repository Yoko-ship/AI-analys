"""Annual attachment discovery does not depend on issuer-specific source lists."""
import json

import pytest

from financial_ingestion import disclosures, documents, extract, store, publication, maintenance
from tests.test_financial_ingestion import setup
import reports_catalog as rc


def listing(org=23, rid=7, kind='bank'):
    return [{'organization': org, 'object_id': rid, 'report_type': 'NSBU',
             'properties': {'org_type': kind, 'report_type': 'annual'}}]


def detail(org=23, rid=7):
    return {'id': rid, 'organization': {'id': org}, 'parent_id': 900,
            'int_report': 'https://openinfo.uz/media/int_report/statements.pdf',
            'audition_result_report': [{'main_report': rid, 'conclusion_file': 'audit_conclusion/opinion.PDF'}]}


def remember(rid=7, org=23, kind='bank'):
    disclosures.remember_listing(ticker='BRBN', org_id=org, records=listing(org,rid,kind))


def test_annual_attachments_found_without_financial_catalog_row_and_never_publish(setup):
    remember()
    result = disclosures.discover(ticker='BRBN', processor=extract.processor_version(), fetch=lambda _: detail())
    assert result == {'sources': 2, 'requests': 1, 'errors': [], 'pending': 0}
    c = store.connect()
    try:
        sources = [dict(r) for r in c.execute('SELECT * FROM ingest_sources')]
        assert {s['category'] for s in sources} == {'MSFO','Audition'}
        assert all(json.loads(s['metadata_json'])['source_page_url'].endswith('/bank/annual/7') for s in sources)
        assert all(json.loads(s['metadata_json'])['disclosure_sha256'] for s in sources)
        assert c.execute('SELECT COUNT(*) FROM ingest_jobs').fetchone()[0] == 2
    finally:c.close()
    assert publication.snapshots('BRBN') == []
    assert disclosures.discover(ticker='BRBNP',processor='same',fetch=lambda _: pytest.fail('cache'))['requests'] == 0


def test_catalog_bootstrap_is_part_of_normal_discovery(setup,monkeypatch):
    c=rc.get_catalog_conn()
    with c:
        rc._upsert_report(c,'BRBN',report_form='NSBU',period_type='annual',year=2020,quarter=0,
                          title='Annual',published_at=None,pdf_url=None,
                          excel_url='https://new-api.openinfo.uz/api/v2/reports/export-excel/?org_type=bank&report_type=annual&report_id=7',
                          excel_url_form1=None,openinfo_report_id='7',object_id=None)
    c.close()
    monkeypatch.setattr(disclosures,'_fetch',lambda _:detail())
    result=documents.discover(processor=extract.processor_version())
    assert result['annual_attachments']['sources']==2
    assert result['annual_attachments']['requests']==1


@pytest.mark.parametrize('change', ['issuer','record','audit_parent','external','traversal','not_pdf'])
def test_rejects_wrong_issuer_and_unsafe_attachments(setup,change):
    remember();d=detail()
    if change=='issuer':d['organization']['id']=99
    if change=='record':d['id']=8
    if change=='audit_parent':d['audition_result_report'][0]['main_report']=8
    if change=='external':d['int_report']='https://outside.example/media/a.pdf'
    if change=='traversal':d['int_report']='https://openinfo.uz/media/%2e%2e/private.pdf'
    if change=='not_pdf':d['int_report']='https://openinfo.uz/media/login.html'
    result=disclosures.discover(ticker='BRBN',processor='test',fetch=lambda _:d)
    assert result['errors'] and result['sources']==0
    assert store.status('23')['discovery_errors']
    assert 'DISCOVERY_FAILED' in maintenance.monitor()['incidents']


def test_failure_retries_and_preserves_verified_attachments(setup):
    remember()
    disclosures.discover(ticker='BRBN',processor='test',fetch=lambda _:detail())
    with store.transaction() as c:c.execute('UPDATE ingest_disclosures SET retry_at=0')
    def fail(_):raise TimeoutError('upstream timeout')
    assert disclosures.discover(ticker='BRBN',processor='test',fetch=fail)['sources']==2
    assert disclosures.discover(ticker='BRBN',processor='test',fetch=fail)['requests']==0
    with store.transaction() as c:c.execute('UPDATE ingest_disclosures SET retry_at=0')
    disclosures.discover(ticker='BRBN',processor='test',fetch=lambda _:detail())
    assert not store.status('23')['discovery_errors']


def test_bounded_resume_negative_cache_and_duplicate_links(setup):
    for rid in range(1,4):remember(rid)
    calls=[]
    def fetch(path):
        rid=int(path.strip('/').split('/')[-1]);calls.append(rid);d=detail(rid=rid)
        d['int_report']=None;d['audition_result_report']=[]
        return d
    assert disclosures.discover(ticker='BRBN',processor='test',max_requests=1,fetch=fetch)['pending']==2
    assert disclosures.discover(ticker='BRBN',processor='test',max_requests=1,fetch=fetch)['pending']==1
    assert disclosures.discover(ticker='BRBN',processor='test',max_requests=1,fetch=fetch)['pending']==0
    assert len(set(calls))==3
    assert disclosures.discover(ticker='BRBN',processor='test',fetch=fetch)['requests']==0
    with store.transaction() as c:c.execute('UPDATE ingest_disclosures SET retry_at=0')
    def dup(path):
        d=detail(rid=int(path.strip('/').split('/')[-1]));d['audition_result_report'][0]['conclusion_file']=d['int_report'];return d
    assert disclosures.discover(ticker='BRBN',processor='test',fetch=dup)['sources']==1


def test_mismatched_listing_and_reassigned_issuer_are_not_discovered(setup):
    disclosures.remember_listing(ticker='BRBN',org_id=23,records=listing(org=99))
    assert disclosures.discover(ticker='BRBN',processor='test',fetch=lambda _:pytest.fail())['requests']==0
    remember()
    with store.transaction() as c:c.execute("UPDATE catalog_companies SET org_id='77' WHERE ticker='BRBN'")
    assert disclosures.discover(processor='test',fetch=lambda _:pytest.fail())['requests']==0


def test_nonbank_attachments_supported_when_requested(setup):
    remember(kind='jsc')
    assert disclosures.discover(processor='test',fetch=lambda _:pytest.fail())['requests']==0
    assert disclosures.discover(ticker='BRBN',processor='test',fetch=lambda _:detail())['sources']==2
