"""Dated issuer ownership and governance, from published/reviewed disclosures.

Reads are local: the existing financial publication and corporate-event collectors
remain the ingestion boundary. Affiliation lists and share counts are not ownership
percentages. A later financial report without owners cannot erase an older table.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from urllib.parse import urlsplit

import dbx
from catalogue.storage import get_catalog_conn
from financial_ingestion import publication

REVIEWED = Path(__file__).resolve().parents[2] / 'config' / 'company_disclosures.json'


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _url(value):
    try:
        parts = urlsplit(value or '')
        return value if parts.scheme in {'https', 'http'} and parts.hostname and not parts.username else None
    except ValueError:
        return None


def _matches(record, issuer_id, tickers):
    if issuer_id and record.get('issuer_id'):
        return str(record['issuer_id']) == issuer_id
    return bool(tickers.intersection(record.get('tickers') or []))


def _empty():
    return {'status': 'unavailable', 'as_of': None, 'source': None, 'items': []}


def _ownership_table(record, today):
    """Reject an invalid table as a unit, retaining its date/class/perimeter."""
    as_of, source = _day(record.get('as_of')), record.get('source') or {}
    if not as_of or as_of > today or not _url(source.get('url')):
        return None
    if record.get('share_class') not in {'ordinary', 'preferred', 'ownership_interest'}:
        return None
    if record.get('scope') not in {'separate', 'consolidated'}:
        return None
    items, names, total = [], set(), Decimal(0)
    for row in record.get('items') or []:
        name = str(row.get('name') or '').strip()
        page = row.get('page') or source.get('page')
        try:
            share = Decimal(str(row.get('share')))
        except InvalidOperation:
            return None
        if (not name or name.casefold() in names or row.get('quality', 'valid') != 'valid'
                or not share.is_finite() or not 0 <= share <= 100
                or not isinstance(page, int) or page < 1):
            return None
        names.add(name.casefold())
        total += share
        items.append({'name': name, 'share': str(share), 'kind': row.get('kind', 'unknown'),
                      'page': page, 'source_url': source['url']})
    if not items or total > 100:
        return None
    return {'status': 'disclosed' if total == 100 else 'partial', 'as_of': as_of,
            'scope': record['scope'], 'share_class': record['share_class'], 'source': source,
            'items': sorted(items, key=lambda row: -Decimal(row['share']))}


def _published_ownership(ticker):
    for scope in ('consolidated', 'separate'):
        for snapshot in publication.snapshots(ticker, scope=scope):
            payload = snapshot['payload']
            groups = defaultdict(list)
            for owner in payload.get('shareholders') or []:
                if owner.get('scope') == scope:
                    groups[(owner.get('date'), owner.get('share_class'))].append(owner)
            evidence = payload.get('source') or {}
            for (as_of, share_class), items in groups.items():
                yield {'as_of': as_of, 'scope': scope, 'share_class': share_class, 'items': items,
                       'source': {'url': evidence.get('pdf_url'), 'file_hash': evidence.get('file_hash'),
                                  'version': snapshot['id'], 'page': items[0].get('page')}}


def _person_key(person):
    # Never match two people by their row numbers, or guess a successor.
    return ' '.join(str(person.get('name') or '').casefold().split())


def _people(rows, doc, as_of):
    vacancies = {'вакансия', 'вакантно', 'vacant', 'vacancy', 'vakant', "bo'sh", 'bo‘sh'}
    return [{**row, 'source_url': doc['source_url'], 'as_of': as_of}
            for row in rows or [] if _person_key(row) and _person_key(row) not in vacancies]


def _management(documents, today):
    dated = []
    for doc in documents:
        published = _day(doc.get('published_at'))
        effective = _day(doc.get('event_date') or doc.get('decision_date'))
        if (doc.get('code') == 8 and effective and published and max(effective, published) <= today
                and _url(doc.get('source_url')) and doc.get('governance')):
            dated.append((effective, doc.get('published_at', ''), doc))
    roster, complete, last = {}, False, None
    for effective, _, doc in sorted(dated, key=lambda row: (row[0], row[1], row[2]['source_url'])):
        groups = doc['governance']
        full = _people(groups.get('roster'), doc, effective)
        appointed = _people(groups.get('appointed'), doc, effective)
        departed = _people(groups.get('departed'), doc, effective)
        if full:
            roster = {_person_key(person): person for person in full}
            complete = True
        else:
            for person in departed:
                roster.pop(_person_key(person), None)
            for person in appointed:
                roster[_person_key(person)] = person
        if full or appointed or departed:
            last = (effective, doc)
    if not last:
        return _empty()
    effective, doc = last
    return {'status': 'disclosed' if complete else 'partial', 'as_of': effective,
            'source': {'url': doc['source_url'], 'published_at': doc['published_at']},
            'items': list(roster.values())}


def load(ticker, *, today=None):
    """Latest evidenced ownership table plus the disclosed governance roster."""
    ticker = ticker.strip().upper()
    today = today or date.today().isoformat()
    reviewed = json.loads(REVIEWED.read_text(encoding='utf-8'))
    conn = get_catalog_conn()
    try:
        company = conn.execute('SELECT org_id FROM catalog_companies WHERE ticker=?', (ticker,)).fetchone()
        issuer_id = str(company['org_id']) if company and company['org_id'] else None
        tickers = {ticker}
        if issuer_id:
            tickers.update(row['ticker'] for row in conn.execute('SELECT ticker FROM catalog_companies WHERE org_id=?', (issuer_id,)))
        stored = []
        if 'corporate_event_documents' in dbx.tables(conn):
            stored = [json.loads(row['document_json']) for row in conn.execute(
                'SELECT document_json FROM corporate_event_documents WHERE published_at < ? AND document_json LIKE ?',
                (today + 'T99', '%"governance"%'))]
    finally:
        conn.close()
    matches = lambda record: _matches(record, issuer_id, tickers)
    candidates = [row for row in reviewed['ownership'] if matches(row)]
    candidates.extend(_published_ownership(ticker))
    tables = [table for row in candidates if (table := _ownership_table(row, today))]
    # Issuer-wide interests win ties over individual share classes; never add them.
    ownership = max(enumerate(tables), key=lambda pair: (
        pair[1]['as_of'], pair[1]['share_class'] == 'ownership_interest',
        pair[1]['scope'] == 'consolidated', pair[0]))[1] if tables else _empty()
    # A collected revision replaces the reviewed copy of the same disclosure.
    documents = {doc['source_url']: doc for doc in reviewed['governance']}
    documents.update({doc['source_url']: doc for doc in stored})
    management = _management([doc for doc in documents.values() if matches(doc)], today)
    return {'ok': True, 'ticker': ticker, 'ownership': ownership, 'management': management}
