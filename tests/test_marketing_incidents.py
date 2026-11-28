"""Source corrections are a separate publication chain, never a retry of old copy."""
from datetime import timedelta

import pytest

from marketing import content, delivery, permissions, store, worker
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401
from test_marketing_delivery import Platform, prepare


def published():
    job = prepare()
    assert delivery.run_one(Platform(), NOW)
    with store.connection() as c:
        return store.get(c, "candidate", job["candidate_id"])


def amend(amount=99, **changes):
    with store.connection() as c:
        old = store.get(c, "evidence", "decision")
    value = {key: old[key] for key in content.Evidence.model_fields}
    return content.save_evidence(OWNER, "decision", {**value, "data": {**value["data"], "dividend": amount}, **changes}, old["version"])


def test_export_preserves_published_evidence_when_the_original_is_later_corrected():
    import io
    import json
    import zipfile
    from marketing import media, publishing
    item = published()
    amend(url='https://openinfo.uz/facts/corrected')
    with store.connection() as c:
        preview = publishing.preview(c, item)
    with zipfile.ZipFile(io.BytesIO(media.export_candidate(item['id']))) as archive:
        package = json.loads(archive.read('material.json'))
        assert package['evidence'][0]['version'] == 1
        assert package['evidence'][0]['data']['dividend'] == 120
        assert archive.read('draft.txt').decode() == preview['text']
        assert package['publication'] == preview


def test_published_preview_keeps_the_platform_used_for_dispatch_after_account_reconfiguration():
    from marketing import publishing
    item = published()
    with store.connection() as c:
        old = store.get(c, 'account', item['account_id'])
    data = {key: old[key] for key in permissions.Account.model_fields}
    permissions.save_account(OWNER, item['account_id'], {**data, 'platform': 'facebook', 'external_id': '123456'}, old['version'])
    with store.connection() as c:
        assert publishing.preview(c, item)['platform'] == 'telegram'


def incident():
    from marketing import incidents
    assert incidents.scan(NOW + timedelta(minutes=1))
    with store.connection() as c:
        return next(row for row in store.list_items(c, "incident") if row["status"] == "open")


def draft(amount=99):
    return {"reason": "В исходном решении исправлен размер дивиденда", "title": "Размер дивиденда уточнён",
            "body": f"Утверждено {amount} сум на простую акцию.", "evidence_ids": ["decision"],
            "claims": [{"evidence_id": "decision", "field": "dividend", "value": amount, "unit": "UZS/share"}],
            "destination_url": "https://uzstock.uz/news/correction", "expires_at": "2026-11-24T07:00:00Z"}


def policy(value):
    with store.connection() as c:
        old = store.get(c, "account", "tg")
    return permissions.save_account(OWNER, "tg", {**{key: old[key] for key in permissions.Account.model_fields},
                                               "correction_policy": value}, old["version"])


def test_changed_published_original_creates_one_incident_without_touching_the_post():
    from marketing import incidents
    original = published()
    amend()
    found = incident()
    assert found["publication_id"] == found["root_candidate_id"] == original["id"]
    assert found["publication"]["external_id"] == "post-123"
    assert found["changes"][0]["before"]["data"]["dividend"] == 120
    assert found["changes"][0]["after"]["data"]["dividend"] == 99
    assert not incidents.scan(NOW + timedelta(minutes=2))
    with store.connection() as c:
        assert store.get(c, "candidate", original["id"]) == original
        assert len(store.list_items(c, "incident")) == 1
        assert len(store.list_items(c, "delivery")) == 1
        assert store.history(c, "evidence", "decision")[0]["record"]["data"]["dividend"] == 120


def test_refresh_dates_alone_do_not_claim_that_a_published_fact_was_wrong():
    from marketing import incidents
    published()
    amend(120, retrieved_at="2026-11-23T08:30:00Z", expires_at="2026-11-25T07:00:00Z")
    assert not incidents.scan(NOW + timedelta(hours=1))
    with store.connection() as c:
        assert store.list_items(c, "incident") == []


def test_worker_detects_corrections_and_obeys_the_processing_pause():
    original = published()
    amend()
    delivery.set_pause(OWNER, processing=True)
    assert not worker.tick(now=NOW + timedelta(minutes=1))["incident_work"]
    delivery.set_pause(OWNER, processing=False)
    assert worker.tick(now=NOW + timedelta(minutes=2))["incident_work"]
    with store.connection() as c:
        assert store.list_items(c, "incident")[0]["publication_id"] == original["id"]


def test_manual_policy_requires_exact_approval_and_only_confirmation_resolves_incident():
    from marketing import incidents
    original = published()
    amend()
    found = incident()
    fixed = incidents.prepare(OWNER, found["id"], found["version"], draft(), NOW + timedelta(minutes=2))
    assert fixed["id"] != original["id"] and fixed["correction_of"] == original["id"]
    assert "Уточнение" in fixed["body"] and "https://t.me/example/123" in fixed["body"]
    checked = content.check_candidate(fixed["id"], NOW + timedelta(minutes=2))
    assert checked["status"] == "awaiting_approval"
    with pytest.raises(MarketingError):
        delivery.schedule(fixed["id"], NOW + timedelta(minutes=2))
    content.approve_candidate(OWNER, fixed["id"], checked["version"])
    delivery.schedule(fixed["id"], NOW + timedelta(minutes=31))
    with store.connection() as c:
        assert store.get(c, "incident", found["id"])["status"] == "correction_prepared"
    transport = Platform({"external_id": "correction-456", "url": "https://t.me/example/456"})
    assert delivery.run_one(transport, NOW + timedelta(minutes=31))
    assert not delivery.run_one(transport, NOW + timedelta(hours=1))
    with store.connection() as c:
        result = store.get(c, "incident", found["id"])
        assert result["status"] == "corrected" and result["correction_publication"]["external_id"] == "correction-456"
        assert store.get(c, "candidate", original["id"]) == original
    assert not incidents.scan(NOW + timedelta(hours=1))
    # A subsequent correction starts at the last confirmed clarification.
    amend(101)
    next_incident = incident()
    assert next_incident["publication_id"] == fixed["id"]
    assert next_incident["changes"][0]["before"]["data"]["dividend"] == 99


def test_authorized_correction_still_stops_when_policy_is_revoked_before_dispatch():
    from marketing import incidents
    published()
    policy("authorized_correction")
    amend()
    found = incident()
    fixed = incidents.prepare(OWNER, found["id"], found["version"], draft(), NOW)
    checked = content.check_candidate(fixed["id"], NOW)
    assert checked["status"] == "ready"
    delivery.schedule(fixed["id"], NOW + timedelta(minutes=31))
    policy("manual")
    transport = Platform()
    assert not delivery.run_one(transport, NOW + timedelta(minutes=31))
    assert transport.calls == []
    assert content.check_candidate(fixed["id"], NOW + timedelta(minutes=31))["status"] == "awaiting_approval"


def test_another_source_change_supersedes_the_incident_and_cannot_send_outdated_clarification():
    from marketing import incidents
    published()
    policy("authorized_correction")
    amend()
    found = incident()
    fixed = incidents.prepare(OWNER, found["id"], found["version"], draft(), NOW)
    content.check_candidate(fixed["id"], NOW)
    delivery.schedule(fixed["id"], NOW)
    amend(101)
    replacement = incident()
    assert replacement["id"] != found["id"]
    assert not delivery.run_one(Platform(), NOW + timedelta(minutes=31))
    with store.connection() as c:
        assert store.get(c, "incident", found["id"])["status"] == "superseded"
        assert store.get(c, "candidate", fixed["id"])["status"] == "skipped"


def test_dismissal_is_an_owner_decision_with_history_not_a_silent_overwrite():
    from marketing import incidents
    published()
    amend(excerpt="Уточнена формулировка", amount=120)
    found = incident()
    with pytest.raises(MarketingError, match="owner"):
        incidents.dismiss({"id": "cmo", "role": "cmo"}, found["id"], found["version"], "Typographic change")
    dismissed = incidents.dismiss(OWNER, found["id"], found["version"], "Изменение не влияет на опубликованный факт")
    assert dismissed["status"] == "not_material"
    assert not incidents.scan(NOW + timedelta(hours=1))
    with store.connection() as c:
        assert store.history(c, "incident", found["id"])[-1]["actor"] == OWNER
        assert len(store.list_items(c, "candidate")) == 1


@pytest.mark.parametrize("change", ["external_id", "platform"])
def test_a_correction_cannot_follow_a_reconfigured_account_to_another_recipient(change):
    from marketing import incidents
    published()
    amend()
    found = incident()
    with store.connection() as c:
        old = store.get(c, "account", "tg")
    permissions.save_account(OWNER, "tg", {**{key: old[key] for key in permissions.Account.model_fields},
        change: "facebook" if change == "platform" else "another-channel"}, old["version"])
    with pytest.raises(MarketingError, match="recipient"):
        incidents.prepare(OWNER, found["id"], found["version"], draft(), NOW)


def test_hidden_correction_label_and_duplicate_preparation_are_blocked():
    from marketing import incidents
    published()
    amend()
    found = incident()
    fixed = incidents.prepare(OWNER, found["id"], found["version"], draft(), NOW)
    with pytest.raises(MarketingError):
        incidents.prepare(OWNER, found["id"], found["version"], draft(), NOW)
    content.revise_candidate(OWNER, fixed["id"], {"body": draft()["body"]}, fixed["version"])
    checked = content.check_candidate(fixed["id"], NOW)
    assert not checked["check"]["passed"] and "correction" in checked["check"]["reason"].lower()


def test_unknown_correction_stays_unresolved_and_is_never_replaced_blindly():
    from marketing import incidents
    published()
    policy("authorized_correction")
    amend()
    found = incident()
    fixed = incidents.prepare(OWNER, found["id"], found["version"], draft(), NOW)
    content.check_candidate(fixed["id"], NOW)
    delivery.schedule(fixed["id"], NOW)
    transport = Platform(TimeoutError("lost response"))
    assert delivery.run_one(transport, NOW + timedelta(minutes=31))
    assert not delivery.run_one(transport, NOW + timedelta(hours=1))
    with store.connection() as c:
        unresolved = store.get(c, "incident", found["id"])
        assert unresolved["status"] == "correction_prepared"
    with pytest.raises(MarketingError):
        incidents.dismiss(OWNER, found["id"], unresolved["version"], "Cannot dismiss an uncertain send")
    amend(101)
    replacement = incident()
    with pytest.raises(MarketingError, match="reconcil"):
        incidents.prepare(OWNER, replacement["id"], replacement["version"], draft(101), NOW)


def test_ordinary_candidates_cannot_impersonate_reserved_correction_events():
    original = published()
    with pytest.raises(MarketingError, match="reserved"):
        content.create_candidate({**{key: original[key] for key in content.Candidate.model_fields},
                                  "event_id": "correction:pretend-incident"})


def test_clarification_must_keep_the_changed_source_or_an_explicit_replacement():
    from marketing import incidents
    published()
    amended = amend()
    found = incident()
    content.save_evidence(OWNER, "replacement", {key: amended[key] for key in content.Evidence.model_fields}, 0)
    value = {**draft(), "evidence_ids": ["replacement"], "claims": [{**draft()["claims"][0], "evidence_id": "replacement"}]}
    with pytest.raises(MarketingError, match="changed source"):
        incidents.prepare(OWNER, found["id"], found["version"], value, NOW)
    fixed = incidents.prepare(OWNER, found["id"], found["version"], {**value, "source_replacements": {"decision": "replacement"}}, NOW)
    assert content.check_candidate(fixed["id"], NOW)["check"]["passed"]
    with store.connection() as c:
        latest = store.get(c, "candidate", fixed["id"])
    content.revise_candidate(OWNER, fixed["id"], {"evidence_ids": ["decision"], "claims": draft()["claims"]}, latest["version"])
    assert "changed source" in content.check_candidate(fixed["id"], NOW)["check"]["reason"]


def test_source_change_during_sending_keeps_one_current_incident_after_confirmation():
    from marketing import incidents
    published()
    policy("authorized_correction")
    amend()
    found = incident()
    fixed = incidents.prepare(OWNER, found["id"], found["version"], draft(), NOW)
    content.check_candidate(fixed["id"], NOW)
    delivery.schedule(fixed["id"], NOW)

    class ChangingPlatform(Platform):
        def publish(self, *args):
            amend(101)
            incident()
            return super().publish(*args)

    assert delivery.run_one(ChangingPlatform(), NOW + timedelta(minutes=31))
    assert incidents.scan(NOW + timedelta(minutes=32))
    with store.connection() as c:
        current = [row for row in store.list_items(c, "incident") if row["status"] == "open"]
        assert len(current) == 1
        assert current[0]["publication_id"] == fixed["id"]
        assert current[0]["changes"][0]["before"]["data"]["dividend"] == 99
        assert current[0]["changes"][0]["after"]["data"]["dividend"] == 101


def test_monitor_records_a_revoked_original_source_without_waiting_for_reingestion():
    from marketing import incidents, sources
    from test_marketing_sources import source_input, article
    from test_marketing_core import account, candidate
    src = sources.save_source(OWNER, "news", source_input(), 0)
    sources.enable_source(OWNER, src["id"], src["version"])
    sources.collect_one(lambda source: [article(data={"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"})], NOW)
    with store.connection() as c:
        ev = store.list_items(c, "evidence")[0]
        src = store.get(c, "source", "news")
    sources.verify_evidence(OWNER, ev["id"], ev["version"], "Compared the issuer decision")
    acc = account(mode="automatic")
    delivery.record_connection("tg", acc["version"], external_id=acc["external_id"], verified=True, now=NOW)
    item = candidate(mode="automatic", evidence_ids=[ev["id"]], claims=[{"evidence_id": ev["id"], "field": "dividend", "value": 120, "unit": "UZS/share"}])
    assert content.check_candidate(item["id"], NOW)["status"] == "ready"
    delivery.schedule(item["id"], NOW)
    assert delivery.run_one(Platform(), NOW)
    sources.enable_source(OWNER, src["id"], src["version"], enabled=False)
    assert incidents.scan(NOW + timedelta(minutes=1))
    with store.connection() as c:
        changed = store.list_items(c, "incident")[0]["changes"][0]
        assert changed["before"]["withdrawn"] is False and changed["after"]["withdrawn"] is True
