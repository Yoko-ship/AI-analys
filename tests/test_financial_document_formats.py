"""Real OpenInfo attachments that previously failed the PDF-only fetch check."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from financial_ingestion import documents, extract, maintenance, store, worker
from tests.test_financial_ingestion import setup

FIXTURES = Path(__file__).parent / 'fixtures' / 'financial_documents'
SOURCES = json.loads((FIXTURES / 'sources.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('source', SOURCES, ids=lambda s: s['fixture'])
def test_real_non_pdf_original_is_fetched_archived_and_backed_up(setup, tmp_path, monkeypatch, source):
    content = (FIXTURES / source['fixture']).read_bytes()
    assert hashlib.sha256(content).hexdigest() == source['sha256']
    with store.transaction() as c:
        documents.register(c, org_id='23', ticker=source['ticker'], url=source['pdf_url'],
                           category='MSFO', metadata={}, processor=extract.processor_version())
    result = worker.run(max_jobs=1, fetch=lambda _: content)
    assert result['outcomes'][0]['ok'], result
    assert documents.read_artifact(source['sha256']) == content
    c = store.connect()
    try:
        artifact = dict(c.execute('SELECT * FROM ingest_artifacts').fetchone())
        assert artifact['media_type'] != 'application/pdf'
        assert not artifact['relative_path'].endswith('.pdf')
        assert c.execute("SELECT COUNT(*) FROM ingest_jobs WHERE stage='EXTRACT' AND state='QUEUED'").fetchone()[0] == 1
    finally:
        c.close()
    monkeypatch.setenv('FINANCIAL_BACKUP_DIR', str(tmp_path / 'backups'))
    assert maintenance.backup()['verified']
    assert (tmp_path / 'backups' / 'objects' / Path(artifact['relative_path']).name).read_bytes() == content


def test_format_upgrade_reopens_only_old_pdf_format_failures(setup):
    with store.transaction() as c:
        for suffix, error in [('word.doc', 'Source did not return a PDF'), ('missing.pdf', '404 Not Found')]:
            url = 'https://openinfo.uz/media/' + suffix
            sid = documents.register(c, org_id='23', ticker='BRBN', url=url, category='MSFO',
                                     metadata={}, processor=extract.processor_version())
            c.execute("UPDATE ingest_jobs SET state='FAILED',processor='bounded-openinfo-v1',attempts=3,error=? WHERE source_id=?",
                      (error, sid))
        documents.register(c, org_id='23', ticker='BRBN', url='https://openinfo.uz/media/word.doc',
                           category='MSFO', metadata={}, processor=extract.processor_version())
        documents.register(c, org_id='23', ticker='BRBN', url='https://openinfo.uz/media/missing.pdf',
                           category='MSFO', metadata={}, processor=extract.processor_version())
        states = [r[0] for r in c.execute('SELECT state FROM ingest_jobs')]
    assert sorted(states) == ['FAILED', 'QUEUED', 'SUPERSEDED']


def test_image_extraction_keeps_original_and_records_rendered_evidence(setup, monkeypatch):
    source = next(s for s in SOURCES if s['fixture'].endswith('.jpg'))
    content = (FIXTURES / source['fixture']).read_bytes()
    with store.transaction() as c:
        documents.register(c, org_id='23', ticker='BRBN', url=source['pdf_url'], category='Audition',
                           metadata={}, processor=extract.processor_version())
    seen = []
    def pages(payload, *, ocr=False):
        assert payload.startswith(b'%PDF-')
        seen.append(ocr)
        return {1: 'Auditor opinion'}, {'page_count': 1, 'ocr_pages': [1], 'ocr_errors': []}
    monkeypatch.setattr(extract, 'page_texts', pages)
    result = worker.run(max_jobs=2, fetch=lambda _: content)
    assert all(o['ok'] for o in result['outcomes']), result
    assert seen == [True]
    c = store.connect()
    try:
        payload = json.loads(c.execute('SELECT payload_json FROM ingest_candidates').fetchone()[0])
        conversion = payload['extraction']['conversion']
        assert conversion['source_sha256'] == source['sha256']
        assert documents.read_artifact(conversion['pdf_sha256']).startswith(b'%PDF-')
        assert payload['page_count'] == 1
        assert c.execute('SELECT COUNT(*) FROM ingest_reviews').fetchone()[0] == 0
    finally:
        c.close()
    assert documents.read_artifact(source['sha256']) == content


@pytest.mark.parametrize('content', [b'<html>Login</html>', b'PK\x03\x04broken', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1broken'])
def test_invalid_or_unrelated_document_does_not_enter_extraction(setup, content):
    with store.transaction() as c:
        documents.register(c, org_id='23', ticker='BRBN', url='https://openinfo.uz/media/report.doc',
                           category='MSFO', metadata={}, processor=extract.processor_version())
    result = worker.run(max_jobs=1, fetch=lambda _: content)
    assert not result['outcomes'][0]['ok']
    c = store.connect()
    try:
        assert c.execute('SELECT COUNT(*) FROM ingest_artifacts').fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM ingest_jobs WHERE stage='EXTRACT'").fetchone()[0] == 0
    finally:
        c.close()


@pytest.mark.parametrize('source', SOURCES, ids=lambda s: s['fixture'])
def test_original_download_uses_actual_media_type(setup, monkeypatch, source):
    import api
    from fastapi.testclient import TestClient
    from financial_ingestion import formats
    content = (FIXTURES / source['fixture']).read_bytes()
    monkeypatch.setattr(documents, 'issuer_artifact', lambda ticker, sha: content)
    response = TestClient(api.app).get('/api/company/BRBN/financials/documents/' + source['sha256'])
    kind = formats.identify(content)
    assert response.content == content
    assert response.headers['content-type'] == formats.MEDIA_TYPES[kind]
    assert response.headers['content-disposition'].endswith('.' + kind + '"')


def test_converter_failure_preserves_fetched_original(setup, monkeypatch):
    from financial_ingestion import formats
    source = next(s for s in SOURCES if s['fixture'].endswith('.doc'))
    content = (FIXTURES / source['fixture']).read_bytes()
    monkeypatch.delenv('LIBREOFFICE_BINARY', raising=False)
    monkeypatch.setattr(formats.shutil, 'which', lambda _: None)
    with store.transaction() as c:
        documents.register(c, org_id='23', ticker='BRBN', url=source['pdf_url'], category='MSFO',
                           metadata={}, processor=extract.processor_version())
    result = worker.run(max_jobs=2, fetch=lambda _: content)
    assert result['outcomes'][0]['ok']
    assert 'WORD_CONVERTER_UNAVAILABLE' in result['outcomes'][1]['reason']
    assert documents.read_artifact(source['sha256']) == content
    c = store.connect()
    try:
        assert c.execute("SELECT state FROM ingest_jobs WHERE stage='FETCH'").fetchone()[0] == 'SUCCEEDED'
        assert c.execute('SELECT COUNT(*) FROM ingest_candidates').fetchone()[0] == 0
    finally:
        c.close()


def test_rendered_pages_remain_available_with_published_original(setup, monkeypatch):
    from financial_ingestion import formats, publication, validation
    from tests.test_financial_ingestion import stage
    stage(setup)
    source = next(s for s in SOURCES if s['fixture'].endswith('.jpg'))
    content = (FIXTURES / source['fixture']).read_bytes()
    with store.transaction() as c:
        documents.register(c, org_id='23', ticker='BRBN', url=source['pdf_url'], category='MSFO',
                           metadata={}, processor=extract.processor_version())
    worker.run(max_jobs=1, fetch=lambda _: content)
    job = store.claim(stages=('EXTRACT',))
    rendered, conversion = documents.extraction_pdf(job, source['sha256'], content)
    monkeypatch.setattr(formats, 'to_pdf', lambda *args: pytest.fail('Rendering must be cached'))
    assert documents.extraction_pdf(job, source['sha256'], content) == (rendered, conversion)
    payload = validation.from_review(setup[0])
    payload['page_count'] = 1
    payload['extraction'] = {'conversion': conversion}
    with store.transaction() as c:
        candidate = store.record_candidate(c, job['version_id'], job['processor'], payload, validation.validate(payload, page_count=1))
    publication.approve(candidate, actor='test', reason='Synthetic approved values test only')
    assert documents.issuer_artifact('BRBN', conversion['pdf_sha256']) is None
    publication.publish('BRBN', actor='test', candidate_ids=[candidate])
    assert documents.issuer_artifact('BRBN', source['sha256']) == content
    assert documents.issuer_artifact('BRBN', conversion['pdf_sha256']) == rendered
    assert documents.issuer_artifact('OCBK', conversion['pdf_sha256']) is None
    passport = publication.passport('BRBN', '2024', 'net_profit')
    assert passport['source']['archived_url'].endswith(source['sha256'])
    assert passport['source']['rendered_url'].endswith(conversion['pdf_sha256'])


@pytest.mark.parametrize('result', ['missing', 'invalid', 'oversize', 'timeout', 'exit', 'ok'])
def test_word_conversion_checks_output_and_has_a_deadline(setup, monkeypatch, result):
    from financial_ingestion import formats
    monkeypatch.setenv('LIBREOFFICE_BINARY', 'test-converter')
    monkeypatch.setattr(formats, 'MAX_BYTES', len(setup[1]) + 1)
    calls = []
    def run(command, **options):
        calls.append(command)
        assert options['timeout'] == 120 and options['check']
        assert '--headless' in command and 'pdf:writer_pdf_Export' in command
        assert (Path(options['cwd']) / 'profile/user/registrymodifications.xcu').exists()
        if result == 'timeout':
            raise subprocess.TimeoutExpired(command, 120)
        if result == 'exit':
            raise subprocess.CalledProcessError(1, command)
        if result != 'missing':
            (Path(options['cwd']) / 'source.pdf').write_bytes(
                b'bad' if result == 'invalid' else b'x' * (formats.MAX_BYTES + 1) if result == 'oversize' else setup[1])
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(formats.subprocess, 'run', run)
    content = (FIXTURES / 'uzhm.docx').read_bytes()
    if result == 'ok':
        assert formats.to_pdf(content, 'docx') == setup[1]
    else:
        with pytest.raises((ValueError, RuntimeError)):
            formats.to_pdf(content, 'docx')
    assert len(calls) == 1


def test_multipage_image_preserves_pages_and_rejects_resource_limits(monkeypatch):
    from financial_ingestion import formats
    import pdfplumber
    output = io.BytesIO()
    first = Image.new('RGB', (30, 60), 'white')
    second = Image.new('RGB', (60, 30), 'black')
    first.save(output, format='TIFF', save_all=True, append_images=[second])
    content = output.getvalue()
    assert formats.identify(content) == 'tiff'
    with pdfplumber.open(io.BytesIO(formats.to_pdf(content, 'tiff'))) as pdf:
        assert len(pdf.pages) == 2
        assert pdf.pages[0].height > pdf.pages[0].width
        assert pdf.pages[1].width > pdf.pages[1].height
    monkeypatch.setattr(formats, 'MAX_IMAGE_PAGES', 1)
    with pytest.raises(ValueError, match='pixel/page limit'):
        formats.identify(content)


def test_docx_expanded_size_limit(monkeypatch):
    from financial_ingestion import formats
    monkeypatch.setattr(formats, 'MAX_BYTES', 100)
    with pytest.raises(ValueError, match='expanded size limit'):
        formats.identify((FIXTURES / 'uzhm.docx').read_bytes())


def test_operational_recovery_only_processes_format_failures_and_never_publishes(setup, tmp_path, monkeypatch):
    from financial_ingestion import formats, recover_formats
    monkeypatch.setenv('FINANCIAL_BACKUP_DIR', str(tmp_path / 'backups'))
    source = next(s for s in SOURCES if s['fixture'].endswith('.docx'))
    content = (FIXTURES / source['fixture']).read_bytes()
    with store.transaction() as c:
        target = documents.register(c, org_id='23', ticker='BRBN', url=source['pdf_url'], category='MSFO',
                                    metadata={}, processor=extract.processor_version())
        c.execute("UPDATE ingest_jobs SET state='FAILED',processor='bounded-openinfo-v1',error='Source did not return a PDF',attempts=3 WHERE source_id=?", (target,))
        unrelated = documents.register(c, org_id='23', ticker='BRBN', url='https://openinfo.uz/media/unrelated.pdf',
                                       category='MSFO', metadata={}, processor=extract.processor_version())
    monkeypatch.setattr(formats, 'to_pdf', lambda *args: setup[1])
    fetched = []
    with monkeypatch.context() as pending:
        pending.setattr(worker, 'run', lambda **kwargs: {'outcomes': []})
        assert not recover_formats.run()['complete']
    def fetch(url):
        fetched.append(url)
        return content
    result = recover_formats.run(fetch=fetch)
    assert result['complete']
    assert result['backup']['verified']
    assert result['selected'] == 1 and fetched == [source['pdf_url']]
    assert result['sources'][0]['source_id'] == target
    assert result['sources'][0]['candidates'] == 1
    c = store.connect()
    try:
        assert c.execute('SELECT state FROM ingest_jobs WHERE source_id=?', (unrelated,)).fetchone()[0] == 'QUEUED'
        assert c.execute('SELECT COUNT(*) FROM ingest_snapshots').fetchone()[0] == 0
    finally:
        c.close()
    again = recover_formats.run(fetch=lambda _: pytest.fail('Completed source must not be downloaded again'))
    assert again['sources'][0]['outcomes'] == []
