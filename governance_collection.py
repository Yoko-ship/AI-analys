"""Discover management disclosures for every catalog issuer, independent of news.

Manual: python -m governance_collection --ticker HMKB --force
All companies: python -m governance_collection --force
Requests use the shared paced/retrying/circuit-breaking Openinfo transport.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json

import requests
import openinfo_http as source
import corporate_events as events
import corporate_event_fields as fields
from corporate_governance import body_for, named_person
from catalogue.storage import get_catalog_conn
from collectors.openinfo.settings import OPENINFO_API_BASE
import governance_store as store

ENDPOINT = OPENINFO_API_BASE + '/disclosure/facts/'


class SourceError(ValueError):
    pass


def _issuers(ticker):
    import securities_catalog
    from entity_resolver import resolve_by_index, get_org_index, _normalize_name_key
    conn = get_catalog_conn()
    try:
        rows = conn.execute('SELECT ticker,org_id FROM catalog_companies ORDER BY ticker').fetchall()
    finally:
        conn.close()
    identities = {row['ticker']: row['org_id'] for row in rows}
    securities = securities_catalog.get_securities_map()
    for symbol, security in securities.items():
        if not identities.get(symbol):
            resolved = resolve_by_index(symbol, security.get('isin'))
            identities[symbol] = resolved.get('org_id') if resolved else None
    # The market can list a share class absent from both report catalogs and
    # today's Openinfo index. Reuse a known issuer only for an exact, unambiguous
    # company name in that same market directory; never fuzzy-match names.
    known_names = {}
    for symbol, security in securities.items():
        name = _normalize_name_key(security.get('name'))
        if name and identities.get(symbol):
            known_names.setdefault(name, set()).add(str(identities[symbol]))
    for symbol, security in securities.items():
        matches = known_names.get(_normalize_name_key(security.get('name')), set())
        if not identities.get(symbol) and len(matches) == 1:
            identities[symbol] = next(iter(matches))
    unresolved = [symbol for symbol in securities if not identities.get(symbol)]
    if unresolved:
        registered = get_org_index().get('by_name') or {}
        for symbol in unresolved:
            exact = registered.get(_normalize_name_key(securities[symbol].get('name'))) or {}
            identities[symbol] = exact.get('org_id')
    issuers, missing = {}, []
    for symbol, value in sorted(identities.items()):
        org = str(value or '').strip()
        if not org.isdigit():
            missing.append(symbol)
        else:
            issuers.setdefault(org, []).append(symbol)
    if ticker:
        wanted = ticker.strip().upper()
        issuers = {key: value for key, value in issuers.items() if wanted in value}
        missing = [value for value in missing if value == wanted]
        if not issuers and not missing:
            raise ValueError('Ticker is not in the company catalog')
    return issuers, missing


def _json(url, params=None):
    response = source.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise SourceError('INVALID_SOURCE_RESPONSE')
    return payload


def _identity(row, issuer_id):
    org = row.get('organization')
    if isinstance(org, dict):
        org = org.get('id')
    if str(org) != issuer_id:
        raise SourceError('ISSUER_MISMATCH')
    if str(row.get('fact_number')) != '8':
        raise SourceError('WRONG_DISCLOSURE_TYPE')


def _complete_executive(document, today):
    governance = document.get('governance') or {}
    effective = events.day(document.get('event_date'))
    published = events.day(document.get('published_at'))
    return (body_for(governance) == 'executive' and any(named_person(row) for row in governance.get('roster') or [])
            and effective and published and max(effective, published) <= today)


def _discover(issuer_id, tickers, previous, cached, now, max_documents):
    checked = now.isoformat()
    receipt = {'issuer_id': issuer_id, 'tickers': tickers, 'checked_at': checked,
               'last_success_at': previous.get('last_success_at'), 'state': 'complete',
               'reason': 'NO_FORM8_DISCLOSURES', 'imported': 0, 'examined': 0,
               'document_checks': dict(previous.get('document_checks') or {})}
    stage, seen, fetched = 'listing', set(), 0
    cutoff = (now - timedelta(days=7)).isoformat()
    try:
        for page in range(1, 21):
            stage = 'listing'
            payload = _json(ENDPOINT, {'organization_id': issuer_id, 'fact_number': 8, 'page_size': 100, 'page': page})
            rows = payload.get('results')
            if not isinstance(rows, list):
                raise SourceError('INVALID_SOURCE_RESPONSE')
            if not rows and payload.get('next'):
                raise SourceError('PAGINATION_STALLED')
            for metadata in rows:
                stage = 'listing'
                _identity(metadata, issuer_id)
                ident = str(metadata.get('id') or '')
                if not ident.isdigit() or ident in seen:
                    raise SourceError('PAGINATION_STALLED')
                seen.add(ident)
                document = cached.get(ident)
                last = receipt['document_checks'].get(ident) or ''
                if not document or document.get('extraction_version') != fields.VERSION or last < cutoff:
                    if fetched >= max_documents:
                        receipt.update(state='partial', reason='ARCHIVE_LIMIT_REACHED')
                        return receipt
                    stage = 'detail'
                    detail = _json(ENDPOINT + ident + '/')
                    raw = detail.get('fact')
                    raw = raw[0] if isinstance(raw, list) and raw else raw
                    if not isinstance(raw, dict):
                        raise SourceError('INVALID_SOURCE_RESPONSE')
                    _identity(raw, issuer_id)
                    if str(raw.get('id')) != str(metadata.get('object_id')):
                        raise SourceError('DISCLOSURE_ID_MISMATCH')
                    document = events.from_fact({**metadata, **raw, 'pub_date': raw.get('pub_date') or metadata.get('pub_date')}, tickers=tickers)
                    document.update(global_fact_id=ident, evidence_checked=True)
                    events.save_documents([document])
                    cached[ident] = document
                    receipt['document_checks'][ident] = checked
                    receipt['imported'] += 1
                    fetched += 1
                receipt['examined'] += 1
                if _complete_executive(document, now.date().isoformat()):
                    receipt.update(reason='EXECUTIVE_ROSTER_FOUND', last_success_at=checked)
                    return receipt
            if not payload.get('next'):
                receipt.update(reason='NO_EXECUTIVE_ROSTER' if seen else 'NO_FORM8_DISCLOSURES', last_success_at=checked)
                return receipt
        receipt.update(state='partial', reason='ARCHIVE_LIMIT_REACHED')
    except source.OpeninfoPaused:
        receipt.update(state='failed', reason='SOURCE_PAUSED', stage=stage)
    except requests.Timeout:
        receipt.update(state='failed', reason='TIMEOUT', stage=stage)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 'ERROR'
        receipt.update(state='failed', reason=f'HTTP_{code}', stage=stage)
    except requests.RequestException:
        receipt.update(state='failed', reason='CONNECTION_ERROR', stage=stage)
    except SourceError as exc:
        receipt.update(state='failed', reason=str(exc), stage=stage)
    except (ValueError, KeyError, TypeError):
        receipt.update(state='failed', reason='INVALID_SOURCE_RESPONSE', stage=stage)
    return receipt


def run(*, ticker=None, limit=100, max_documents=30, force=False, now=None, progress=None):
    now = now or datetime.now(timezone.utc)
    issuers, missing = _issuers(ticker)
    previous, cached = store.receipts(), store.documents()
    cutoff = (now - timedelta(days=1)).isoformat()
    pending = [key for key in issuers if force or previous.get(key, {}).get('checked_at', '') <= cutoff
               or set(issuers[key]) != set(previous.get(key, {}).get('tickers') or [])]
    pending.sort(key=lambda key: previous.get(key, {}).get('checked_at', ''))
    selected = pending[:max(0, limit)]
    result = {'attempted': 0, 'imported': 0, 'failed': 0, 'partial': 0, 'remaining': len(pending)-len(selected),
              'missing_identity': missing, 'companies': []}
    for issuer_id in selected:
        receipt = _discover(issuer_id, issuers[issuer_id], previous.get(issuer_id, {}), cached,
                            now, max(1, max_documents))
        store.save(issuer_id, receipt)
        result['attempted'] += 1
        result['imported'] += receipt['imported']
        result['failed'] += receipt['state'] == 'failed'
        result['partial'] += receipt['state'] == 'partial'
        public = {key: value for key, value in receipt.items() if key != 'document_checks'}
        result['companies'].append(public)
        if progress:
            progress(public)
        if receipt['reason'] == 'SOURCE_PAUSED':
            result['remaining'] += len(selected) - result['attempted']
            break
    return result


def report_receipt(row):
    from collection_ops.model import receipt
    stage = 'governance:' + ','.join(row['tickers'])
    if row['imported']:
        receipt(stage, ok=True, phase='publication', counts={'written': row['imported']})
    receipt(stage + ':' + row.get('stage', 'discovery'),
            ok=row['state'] == 'complete', reason=row['reason'],
            unchanged=row['state'] == 'complete' and not row['imported'])
    print(json.dumps({'governance': row}, ensure_ascii=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--max-documents', type=int, default=30)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    result = run(**vars(args), progress=report_receipt)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
