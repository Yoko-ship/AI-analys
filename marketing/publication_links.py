"""Public opaque links bound to an immutable draft and confirmed release.

The canonical destination remains the input to report validation. The outgoing
URL is reviewed separately and never supplies a browser-asserted channel.
"""
import hashlib
import json
import secrets
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from . import store as s
from .permissions import timestamp

PARAM = 'uz_pub'
DECORATIONS = {PARAM, 'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'utm_id', 'fbclid', 'gclid', 'li_fat_id'}
ACTOR = {'id': 'publication_links', 'role': 'coordinator'}


def _browser_path(path):
    """WHATWG special-URL dot segments, preserving encoded slashes and empties."""
    parts, normalized = (path or '/').split('/'), []
    for index, part in enumerate(parts):
        dot = part.lower().replace('%2e', '.')
        if dot in {'.', '..'}:
            if dot == '..' and len(normalized) > 1:
                normalized.pop()
            if index == len(parts)-1:
                normalized.append('')
        else:
            normalized.append(part)
    return quote('/'.join(normalized) or '/', safe="/%:@!$&'()*+,;=-._~[]^|")


def fingerprint(url):
    """Match the browser's route, keeping duplicate parameter order and fragment."""
    parts = urlsplit(url)
    pairs = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in DECORATIONS]
    pairs.sort(key=lambda pair: pair[0].encode('utf-16-be'))
    path = _browser_path(parts.path)
    fragment = quote(parts.fragment, safe="/%?:@!$&'()*+,;=-._~#[]^|{}")
    value = json.dumps([path, pairs, '#' + fragment if fragment else ''], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()


def valid_destination(url):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.hostname in {'uzstock.uz', 'www.uzstock.uz'} and p.port in {None, 443}
                and not p.username and not p.password and _browser_path(p.path) not in {'', '/'}
                and PARAM not in dict(parse_qsl(p.query, keep_blank_values=True))
                and not any(ord(char) <= 32 or char == '\\' for char in url))
    except ValueError:
        return False


def basis(item):
    from .models import Candidate
    return s.digest({key: item.get(key) for key in Candidate.model_fields if key not in {'digest_items', 'occasion'} or key in item})


def issue(c, item):
    if not item.get('track_visits') or not valid_destination(item['destination_url']):
        return None
    from .reports import settings
    account = s.get(c, 'account', item['account_id'], required=False)
    if not account:
        return None
    token = secrets.token_urlsafe(24)
    parts = urlsplit(item['destination_url'])
    outgoing = urlunsplit(parts._replace(query=parts.query + ('&' if parts.query else '') + urlencode({PARAM: token})))
    value = {'id': token, 'candidate_id': item['id'], 'basis': basis(item), 'dataset': settings(c)['data']['dataset'],
             'channel': account['platform'], 'external_account_id': account['external_id'], 'promotion': item['publication_type'],
             'destination': outgoing, 'fingerprint': fingerprint(item['destination_url'])}
    s.put(c, 'publication_link', value, actor=ACTOR, action='publication_link_issued', expected_version=0)
    return {'token': token, 'destination': outgoing, 'dataset': value['dataset'], 'basis': value['basis']}


def destination(item):
    return (item.get('tracking') or {}).get('destination') or item['destination_url']


def _matches(item, link):
    return bool(link and link['candidate_id'] == item['id'] and link['basis'] == basis(item)
                and item.get('tracking') == {'token': link['id'], 'destination': link['destination'], 'dataset': link['dataset'], 'basis': link['basis']})


def check(c, item):
    failures = _generated_destination(c, item)
    if not item.get('track_visits'):
        return failures
    tracking = item.get('tracking') or {}
    link = s.get(c, 'publication_link', tracking.get('token', ''), required=False)
    account = s.get(c, 'account', item['account_id'], required=False)
    if (not _matches(item, link) or not account or account['platform'] != link['channel']
            or account['external_id'] != link['external_account_id']):
        failures.append('Publication tracking requires a valid, unchanged UZStock destination and content version')
    return failures


def _generated_destination(c, item):
    """An untrusted writer chooses only a reviewed destination, never a URL guess."""
    if not item.get('origin_task'):
        return []  # The owner explicitly supplied this candidate's destination.
    task = s.get(c, 'task', item['origin_task'], required=False)
    scope = (task or {}).get('production')
    if not scope:
        return ['Generated content has no recorded production scope for its destination']
    review = item.get('destination_review') or {}
    if review.get('actor') is not None and all(review.get(key) == item[key] for key in ('account_id', 'event_id')) and review.get('url') == item['destination_url']:
        allowed = [review['url']]
    elif scope.get('destination_url'):
        allowed = [scope['destination_url']]
    else:
        from . import sources
        allowed = [original['destination_url'] for key in item['evidence_ids']
                   if key in task['evidence_versions'] and (original := sources.current_evidence(c, key))
                   and original.get('destination_url')]
    allowed = [url for url in allowed if valid_destination(url)]
    if not allowed:
        return ['Generated publication needs a reviewed destination from the owner brief or selected originals']
    if not valid_destination(item['destination_url']) or fingerprint(item['destination_url']) not in {fingerprint(url) for url in allowed}:
        return ['Generated destination differs from the owner brief or selected originals']
    return []


def resolve(c, token, proof, received_at, cut, dataset):
    """Only confirmed copy can credit an arrival; late visibility is replayable."""
    from .content import content_digest
    link = s.get(c, 'publication_link', token, required=False)
    if not link or link['fingerprint'] != proof or link['dataset'] != dataset:
        return None
    item = s.get(c, 'candidate', link['candidate_id'], required=False)
    job = s.get(c, 'delivery', link['candidate_id'], required=False)
    if (not item or not job or item['status'] != 'published' or job['status'] != 'published'
            or timestamp(item['updated_at']) > cut or timestamp(job['updated_at']) > cut
            or timestamp(link['updated_at']) > received_at or received_at > cut
            or (item.get('tracking') or {}).get('token') != token or not _matches(item, link)
            or job.get('external_account_id') != link['external_account_id']
            or job.get('content_digest') != content_digest(item)
            or not job.get('provider_requested_at') or timestamp(job['provider_requested_at']) > received_at):
        return None
    return {'publication_id': item['id'], 'channel': link['channel'], 'promotion': link['promotion']}
