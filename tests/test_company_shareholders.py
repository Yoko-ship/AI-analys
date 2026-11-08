"""Issuer ownership is dated evidence, never inferred from related-party lists."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from catalogue.storage import get_catalog_conn
from corporate_events import from_fact, save_documents
from server.company.financial_routes import router

app = FastAPI()
app.include_router(router)


@pytest.fixture(autouse=True)
def catalog(monkeypatch, tmp_path):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    with get_catalog_conn() as conn:
        conn.executemany('INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES (?,?,?)',
                         [('HMKB', 'Hamkorbank', '8'), ('HMKBP', 'Hamkorbank', '8'),
                          ('IPTB', 'Ipoteka-bank', '17'), ('IPTBP', 'Ipoteka-bank', '17'),
                          ('UZGF', 'Uzgeofizika', '99')])


def load(ticker):
    from server.company.shareholders import load
    return load(ticker, today='2026-11-08')


def iptb_document():
    raw = json.loads(Path('tests/fixtures/openinfo/iptb_2026_governance.json').read_text(encoding='utf-8'))['raw']
    return from_fact(raw)


@pytest.mark.parametrize('fixture_name,body', [
    ('agmkp_governance', 'supervisory'),
    ('grbk_governance', 'unspecified'),
    ('cbsk_governance', 'executive'),
    ('miqe_governance', 'executive'),
    ('iptb_2026_governance', 'executive'),
    ('brbn_governance', 'executive'),
    ('drbk_governance', 'executive'),
    ('ocbk_governance', 'executive'),
])
def test_real_filings_do_not_label_other_employers_directors_as_company_executives(fixture_name, body):
    raw = json.loads(Path(f'tests/fixtures/openinfo/{fixture_name}.json').read_text(encoding='utf-8'))['raw']
    assert from_fact(raw)['governance']['body'] == body


def test_unidentified_body_changes_are_not_merged_into_another_unidentified_roster():
    raw = json.loads(Path('tests/fixtures/openinfo/grbk_governance.json').read_text(encoding='utf-8'))['raw']
    older = from_fact(raw)
    newer = copy.deepcopy(older)
    newer.update(source_url='https://openinfo.uz/ru/facts/8/16001', published_at='2026-11-06T10:00:00', event_date='2026-11-05')
    newer['governance'].update(roster=[], departed=[], appointed=[{
        'name': 'A newly disclosed member', 'position': 'Director', 'work_place': 'An external company'}])
    save_documents([older, newer])
    result = load('GRBK')['management']
    assert result['body'] == 'unspecified'
    assert result['status'] == 'partial'
    assert [p['name'] for p in result['items']] == ['A newly disclosed member']


def test_hmkb_reviewed_2025_table_has_exact_percentages_and_page():
    result = load('HMKB')['ownership']
    assert result['as_of'] == '2025-12-31'
    assert result['source']['page'] == 13
    assert result['source']['url'].endswith('ba173c49-969f-48b2-8657-64d386332c52.pdf')
    assert len(result['source']['file_hash']) == 64
    assert {row['name']: row['share'] for row in result['items']} == {
        'Ibragimov Ikram': '59.21',
        'Nederlandse Financierings-Maatschappij Voor Ontwikkelingslanden n.v. (FMO)': '14.55',
        'ResponsAbility Participations Aktiengesellschaft': '10.53',
        'International Finance Corporation': '7.28',
        'ResponsAbility Sicav (lux) micro and SME finance leaders': '2.68',
        'Motonak Capital Management Pte. Ltd': '1.22',
        'Others, individually owning less than 1%': '4.53',
    }
    assert load('HMKBP')['ownership'] == result


def test_iptb_real_form8_roster_excludes_departed_people_and_vacancy():
    doc = iptb_document()
    save_documents([doc])
    result = load('IPTB')['management']
    assert result['as_of'] == '2026-10-28'
    assert result['source']['url'] == 'https://openinfo.uz/ru/facts/8/15218'
    assert len(result['items']) == 8
    assert result['items'][0]['name'] == 'Сентпетери Адам'
    names = {row['name'] for row in result['items']}
    assert {'Мартон Миклош Ратки', 'Данилин Михаил Алексеевич'} <= names
    assert not {'Вакансия', 'Элашвили Иракли', 'Быков Максим'} & names
    assert result['status'] == 'disclosed'
    assert load('IPTBP')['management'] == result


def test_reviewed_governance_is_available_before_collector_backfill():
    result = load('IPTB')['management']
    assert [p['name'] for p in result['items']] == [p['name'] for p in iptb_document()['governance']['roster'] if p['name'] != 'Вакансия']


def test_hmkb_newer_supervisory_filing_cannot_replace_executive_management():
    for name in ['executive', 'supervisory']:
        fixture = json.loads(Path(f'tests/fixtures/openinfo/hmkb_2026_{name}.json').read_text(encoding='utf-8'))
        save_documents([from_fact(fixture['raw'])])
    result = load('HMKB')['management']
    assert result['as_of'] == '2026-06-08'
    assert result['body'] == 'executive'
    assert result['source']['url'] == 'https://openinfo.uz/ru/facts/8/14825'
    assert len(result['items']) == 7
    assert result['items'][0]['name'] == 'Ющак Рафал Марцин (Juszcak Rafal Marcin)'
    assert not any('Компаньон' in (p.get('work_place') or '') for p in result['items'])


def test_supervisory_only_filing_is_labelled_as_supervisory():
    fixture = json.loads(Path('tests/fixtures/openinfo/hmkb_2026_supervisory.json').read_text(encoding='utf-8'))
    save_documents([from_fact(fixture['raw'])])
    result = load('HMKB')['management']
    assert result['body'] == 'supervisory'
    assert result['items'][-1]['work_place'] == 'ЗАО «Банк Компаньон»'


def test_later_change_only_disclosure_does_not_erase_existing_roster():
    doc = iptb_document()
    changed = copy.deepcopy(doc)
    changed.update(source_url='https://openinfo.uz/ru/facts/8/15219', published_at='2026-11-07T10:00:00',
                   event_date='2026-11-06', decision_date='2026-11-06')
    changed['governance'] = {'roster': [], 'departed': [doc['governance']['roster'][1]],
                             'appointed': [{'name': 'Новый руководитель', 'position': 'Заместитель председателя правления'}]}
    save_documents([changed])
    result = load('IPTB')['management']
    names = [p['name'] for p in result['items']]
    assert len(names) == 8
    assert 'Сентпетери Адам' in names and 'Новый руководитель' in names
    assert 'Виктор Воробей' not in names
    assert result['as_of'] == '2026-11-06'
    assert next(p for p in result['items'] if p['name'] == 'Новый руководитель')['source_url'] == changed['source_url']


def test_partial_governance_is_labelled_and_ownership_is_not_inferred():
    doc = iptb_document()
    doc.update(tickers=['UZGF'], issuer_id='99')
    doc['governance']['roster'] = []
    save_documents([doc])
    result = load('UZGF')
    assert result['management']['status'] == 'partial'
    assert len(result['management']['items']) == 2
    assert result['ownership']['items'] == []
    assert result['ownership']['status'] == 'unavailable'


def test_future_governance_is_not_applied():
    doc = iptb_document()
    doc.update(source_url='https://openinfo.uz/ru/facts/8/16000', published_at='2026-11-08T10:00:00',
               event_date='2026-12-01', decision_date='2026-12-01')
    doc['governance']['roster'] = [{'name': 'Future person', 'position': 'Chair'}]
    save_documents([doc])
    assert 'Future person' not in [p['name'] for p in load('IPTB')['management']['items']]


def snapshot(date, owners):
    return {'id': date, 'period_end': date, 'scope': 'consolidated', 'payload': {
        'source': {'pdf_url': 'https://openinfo.uz/media/msfo/example.pdf'}, 'shareholders': owners}}


def owner(name='Owner', share='60', date='2026-06-30', **changes):
    return {'name': name, 'share': share, 'date': date, 'scope': 'consolidated',
            'share_class': 'ownership_interest', 'quality': 'valid', 'page': 3, **changes}


def test_newest_ownership_table_survives_later_report_without_owners(monkeypatch):
    from financial_ingestion import publication
    rows = [snapshot('2026-06-30', [owner()]), snapshot('2026-09-30', [])]
    monkeypatch.setattr(publication, 'snapshots', lambda ticker, scope=None: rows if scope == 'consolidated' else [])
    result = load('HMKB')['ownership']
    assert result['as_of'] == '2026-06-30'
    assert result['items'][0]['name'] == 'Owner'
    assert result['status'] == 'partial'  # Do not invent an "other" 40%.


@pytest.mark.parametrize('owners', [
    [owner(share='NaN')], [owner(share='-1')], [owner(share='101')],
    [owner(), owner('Other', share='50')], [owner(quality='blocked')],
    [owner(date='2027-01-01')], [owner(page=None)],
])
def test_invalid_published_ownership_does_not_replace_verified_table(monkeypatch, owners):
    from financial_ingestion import publication
    monkeypatch.setattr(publication, 'snapshots', lambda ticker, scope=None: [snapshot('2026-06-30', owners)] if scope == 'consolidated' else [])
    assert load('HMKB')['ownership']['as_of'] == '2025-12-31'


def test_ownership_dates_and_share_classes_are_not_combined(monkeypatch):
    from financial_ingestion import publication
    rows = [owner(), owner('Comparative', date='2025-06-30'), owner('Preferred owner', share_class='preferred')]
    monkeypatch.setattr(publication, 'snapshots', lambda ticker, scope=None: [snapshot('2026-06-30', rows)] if scope == 'consolidated' else [])
    result = load('HMKB')['ownership']
    assert [r['name'] for r in result['items']] == ['Owner']


def test_admin_route_access_private_etag_and_unknown_company_empty_state(monkeypatch):
    import web_auth
    monkeypatch.setenv('ADMIN_EMAILS', 'admin@example.test')
    monkeypatch.setenv('ADMIN_ROLES', '{"analyst@example.test": "analyst"}')
    monkeypatch.setattr(web_auth.web_auth_store.sessions, 'get_user_by_token',
                        lambda token: None if token == 'expired' else SimpleNamespace(
                            id=41, email=f'{token}@example.test', email_verified=True))
    path = '/api/company/HMKBP/shareholders'
    admin = {'Authorization': 'Bearer admin'}
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        for token, status in [('expired', 401), ('reader', 403), ('analyst', 403)]:
            assert client.get(path, headers={'Authorization': f'Bearer {token}'}).status_code == status
        response = client.get(path, headers=admin)
        assert response.status_code == 200
        assert response.json()['ownership']['items'][0]['share'] == '59.21'
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['vary'] == 'Authorization'
        conditional = {'If-None-Match': response.headers['etag']}
        assert client.get(path, headers=conditional).status_code == 401
        assert client.get(path, headers={**conditional, 'Authorization': 'Bearer reader'}).status_code == 403
        cached = client.get(path, headers={**admin, **conditional})
        assert cached.status_code == 304
        assert cached.headers['cache-control'] == 'private, no-store'
        unknown = client.get('/api/company/UNKNOWN/shareholders', headers=admin).json()
        assert unknown['ownership']['items'] == unknown['management']['items'] == []
