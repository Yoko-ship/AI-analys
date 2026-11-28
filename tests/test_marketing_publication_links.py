"""Publication links belong to reviewed copy, never an arbitrary browser channel."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from marketing import content, publishing, store
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401


@pytest.mark.parametrize('case', json.loads((Path(__file__).parent / 'fixtures/publication-routes.json').read_text(encoding='utf-8')))
def test_destination_fingerprint_matches_browser_url_normalization(case):
    from marketing.publication_links import fingerprint
    expected = hashlib.sha256(json.dumps(case['route'], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    assert fingerprint(case['url']) == expected


def test_outgoing_link_preserves_exact_report_and_is_part_of_manual_approval():
    account(mode='manual')
    evidence()
    destination = 'https://uzstock.uz/company/HMKB?standard=ifrs&scope=consolidated&lang=uz&version=v2#report'
    item = candidate(mode='manual', track_visits=True, destination_url=destination,
                     body='Утверждено 120 сум на простую акцию. ' + destination)
    with store.connection() as c:
        preview = publishing.preview(c, item)
    outgoing = preview['tracked_destination']
    assert outgoing != destination and item['destination_url'] == destination
    parsed = urlsplit(outgoing)
    assert parsed.fragment == 'report'
    assert parse_qs(parsed.query)['version'] == ['v2']
    assert len(parse_qs(parsed.query)['uz_pub'][0]) == 32
    assert preview['text'].count(outgoing) == 1
    assert preview['tracking_dataset'] == 'production'
    checked = content.check_candidate(item['id'], NOW)
    assert checked['status'] == 'awaiting_approval', checked['check']['reason']
    approved = content.approve_candidate(OWNER, item['id'], checked['version'])
    revised = content.revise_candidate(OWNER, item['id'], {'body': 'A revised explanation.'}, approved['version'])
    assert revised['check'] is None and revised['approval'] is None
    assert revised['tracking']['token'] != approved['tracking']['token']
    assert content.content_digest(revised) != approved['approval']['content_digest']
    assert candidate(mode='manual', track_visits=True)['tracking'] == revised['tracking']


def test_untracked_legacy_digest_and_exact_profile_destination_remain_explicit():
    from marketing import instagram_links, publication_links
    from marketing.delivery import StoppedBeforeSend
    account(platform='instagram')
    item = candidate(track_visits=True, instagram_link='profile')
    with store.connection() as c:
        outgoing = publishing.preview(c, item)['link_destination']
    assert outgoing != item['destination_url']
    profile = {'id': '123', 'website': item['destination_url']}
    with pytest.raises(StoppedBeforeSend):
        instagram_links.verify({'external_id': '123'}, item, lambda *a, **k: profile, lambda: NOW)
    profile['website'] = outgoing
    assert instagram_links.verify({'external_id': '123'}, item, lambda *a, **k: profile, lambda: NOW)['url'] == outgoing
    legacy = {k: v for k, v in item.items() if k not in {'tracking', 'track_visits', 'instagram_link'}}
    expected = store.digest({k: legacy.get(k) for k in content.Candidate.model_fields if k not in {'track_visits', 'instagram_link'}})
    assert content.content_digest(legacy) == expected
    assert item['destination_url'] in publishing.text(legacy, {})
    # A previously issued link predates structured digest items. Loading it
    # must not invent a new field in the immutable content basis.
    before_items = {key: value for key, value in item.items() if key != 'digest_items'}
    old_basis = store.digest({key: before_items.get(key) for key in content.Candidate.model_fields if key != 'digest_items'})
    before_items['tracking'] = {**item['tracking'], 'basis': old_basis}
    with store.connection(write=True) as c:
        link = store.get(c, 'publication_link', item['tracking']['token'])
        store.put(c, 'publication_link', {**link, 'basis': old_basis}, actor=OWNER,
                  action='pre_digest_basis_fixture', expected_version=link['version'])
        assert not publication_links.check(c, before_items)


def test_account_identity_change_requires_rebinding_before_review():
    from marketing import permissions
    old = account()
    evidence()
    item = candidate(track_visits=True, mode='manual')
    data = {key: old[key] for key in permissions.Account.model_fields}
    permissions.save_account(OWNER, 'tg', {**data, 'external_id': '-100456'}, old['version'])
    assert not content.check_candidate(item['id'], NOW)['check']['passed']


@pytest.mark.parametrize('suffix', ['.', ')', '!', ''])
def test_outgoing_link_replaces_a_punctuated_exact_destination_without_changing_other_urls(suffix):
    account()
    destination = 'https://uzstock.uz/news/123'
    body = f'Read ({destination}{suffix}\nOther: {destination}.json'
    item = candidate(track_visits=True, body=body, destination_url=destination)
    copy = publishing.text(item, {})
    assert 'Read (' + item['tracking']['destination'] + suffix in copy
    assert f'Other: {destination}.json' in copy
    assert copy.count(item['tracking']['destination']) == 1


def test_link_resolution_requires_exact_destination_publication_dataset_and_receipt_boundary(monkeypatch):
    from marketing import publication_links as links
    monkeypatch.setattr(store, 'now', lambda: (NOW-timedelta(hours=1)).isoformat())
    account()
    item = candidate(track_visits=True)
    token = item['tracking']['token']
    fingerprint = links.fingerprint(item['destination_url'])
    with store.connection() as c:
        assert links.resolve(c, token, fingerprint, NOW, NOW, 'production') is None
    monkeypatch.setattr(store, 'now', lambda: NOW.isoformat())
    with store.connection(write=True) as c:
        item = store.put(c, 'candidate', {**item, 'status': 'published'}, actor=OWNER, action='test_confirmed', expected_version=item['version'])
        store.put(c, 'delivery', {'id': item['id'], 'candidate_id': item['id'], 'status': 'published',
            'external_account_id': '-100123',
            'content_digest': content.content_digest(item), 'provider_requested_at': (NOW-timedelta(minutes=5)).isoformat()},
            actor=OWNER, action='test_receipt', expected_version=0)
        assert links.resolve(c, token, fingerprint, NOW-timedelta(minutes=3), NOW, 'production') == {
            'publication_id': item['id'], 'channel': 'telegram', 'promotion': 'organic'}
        for received, cut, dataset, proof in [
            (NOW-timedelta(minutes=6), NOW, 'production', fingerprint),
            (NOW, NOW-timedelta(seconds=1), 'production', fingerprint),
            (NOW, NOW, 'test', fingerprint),
            (NOW, NOW, 'production', '0'*64),
        ]:
            assert links.resolve(c, token, proof, received, cut, dataset) is None
        changed = {**item, 'body': 'Unreviewed change'}
        store.put(c, 'candidate', changed, actor=OWNER, action='test_tamper', expected_version=item['version'])
        assert links.resolve(c, token, fingerprint, NOW, NOW, 'production') is None


def test_destination_fingerprint_ignores_only_tracking_decorations_and_preserves_route_selectors():
    from marketing.publication_links import fingerprint
    base = 'https://uzstock.uz/uz/company/HMKB?scope=consolidated&version=v2#report'
    same = 'https://uzstock.uz/uz/company/HMKB?fbclid=abc&version=v2&uz_pub=abc&scope=consolidated&utm_source=telegram#report'
    assert fingerprint(base) == fingerprint(same)
    assert fingerprint(base) != fingerprint(base.replace('v2', 'v3'))
    assert fingerprint(base) != fingerprint(base.replace('#report', '#financials'))
    assert fingerprint(base) != fingerprint(base.replace('/uz/', '/en/'))
    assert fingerprint(base + '?private=value') != fingerprint(base)


@pytest.mark.parametrize('destination', ['https://evil.example/news/1', 'http://uzstock.uz/news/1',
    'https://uzstock.uz/news/1?uz_pub=forged', 'https://uzstock.uz:999/news/1',
    'https://uzstock.uz/news/../', 'https://uzstock.uz/news/%2e%2e/'])
@pytest.mark.parametrize('tracking', [True, False])
def test_tracking_cannot_silently_replace_an_unsafe_or_pre_tagged_destination(destination, tracking):
    account()
    evidence()
    item = candidate(track_visits=tracking, destination_url=destination)
    checked = content.check_candidate(item['id'], NOW)
    assert not checked['check']['passed']
    assert not item.get('tracking')
