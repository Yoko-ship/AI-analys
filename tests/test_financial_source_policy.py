"""Future source restrictions never remove historical publications."""
import json

import pytest

import ifrs_financials
from financial_ingestion import documents, extract, publication, source_policy, store, worker
from test_financial_ingestion import setup, candidates


def test_default_requires_openinfo_before_network(monkeypatch):
    monkeypatch.delenv('FINANCIAL_SOURCE_POLICY', raising=False)
    monkeypatch.setattr(ifrs_financials.requests, 'get', lambda *a, **k: pytest.fail('network'))
    assert source_policy.allows('https://openinfo.uz/media/new-year/report.pdf')
    for url in ('https://issuer.example/report.pdf', 'https://openinfo.uz/reports/test.pdf',
                'https://openinfo.uz.evil.example/media/test.pdf'):
        with pytest.raises(ValueError, match='OpenInfo-only'):
            ifrs_financials.download_pdf(url, issuer_origin='https://issuer.example')
        with pytest.raises(ValueError, match='OpenInfo-only'):
            documents.register_issuer_source(ticker='BRBN', url=url,
                source_page='https://issuer.example', actor='test', reason='test', processor='test')


def historical_issuer(setup, monkeypatch):
    monkeypatch.setenv('FINANCIAL_SOURCE_POLICY', 'reviewed_issuers')
    setup[0].update(source_kind='issuer_website', source_page_url='https://issuer.example/reports',
                    pdf_url='https://issuer.example/report.pdf', document_year=2024)
    with store.transaction() as c:
        c.execute('DELETE FROM catalog_reports')
    documents.discover(ticker='BRBN', processor=extract.processor_version())
    result = worker.run(max_jobs=4, fetch=lambda _: setup[1])
    assert all(r['ok'] for r in result['outcomes'])
    return candidates()[0]


def test_preserves_published_issuer_but_blocks_new_revision(setup, monkeypatch):
    original = historical_issuer(setup, monkeypatch)
    published = publication.publish('BRBN', actor='test')
    before = publication.series('BRBN')
    passport = publication.passport('BRBN', '2024', 'net_profit')
    monkeypatch.setenv('FINANCIAL_SOURCE_POLICY', 'openinfo')
    assert publication.series('BRBN') == before
    assert publication.passport('BRBN', '2024', 'net_profit') == passport
    assert documents.issuer_artifact('BRBN', setup[0]['sha256']) == setup[1]
    assert publication.publish('BRBN', actor='test') == published
    payload = json.loads(original['payload_json'])
    payload['figures']['net_income']['raw_value'] = '1'
    revised = publication.propose(original['id'], payload, actor='test', reason='revision')
    publication.approve(revised, actor='test', reason='checked')
    with pytest.raises(ValueError, match='OpenInfo-only'):
        publication.publish('BRBN', actor='test', replace=True, candidate_ids=[revised])
    assert publication.series('BRBN') == before


def test_retires_external_queue_and_discovery_cannot_revive_it(setup, monkeypatch):
    historical_issuer(setup, monkeypatch)
    with store.transaction() as c:
        c.execute('UPDATE ingest_sources SET checked_at=1')
    documents.discover(ticker='BRBN', processor='future-parser')
    monkeypatch.setenv('FINANCIAL_SOURCE_POLICY', 'openinfo')
    result = worker.run(max_jobs=4, fetch=lambda _: pytest.fail('external fetch'))
    assert result['processed'] == 0
    assert result['coverage']['jobs']['SUPERSEDED'] == 2
    assert result['coverage']['retained_external_sources'] == 1
    assert result['coverage']['overdue_sources'] == 0
    documents.discover(ticker='BRBN', processor='another-parser')
    assert store.claim() is None
    with store.transaction() as c:
        documents.register(c, org_id='23', ticker='BRBN', url='https://openinfo.uz/media/new.pdf',
            category='MSFO', metadata={}, processor=extract.processor_version())
    job = store.claim()
    assert job['stage'] == 'FETCH'
    documents.fetch_job(job, extract.processor_version(), fetch=lambda _: setup[1])
    assert store.status('23')['jobs']['SUCCEEDED'] == 3
