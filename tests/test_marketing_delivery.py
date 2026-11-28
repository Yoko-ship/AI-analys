"""Transport tests never contact a real social account."""
from datetime import timedelta

import pytest

from marketing import content, delivery, permissions, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401


class Platform:
    def __init__(self, outcome=None):
        self.calls = []
        self.outcome = outcome or {"external_id": "post-123", "url": "https://t.me/example/123"}

    def publish(self, destination, item, release_key):
        self.calls.append((destination["external_id"], item["id"], release_key))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def prepare(mode="automatic"):
    a = account(mode=mode)
    delivery.record_connection("tg", a["version"], external_id=a["external_id"], verified=True, now=NOW)
    evidence()
    item = candidate(mode=mode)
    checked = content.check_candidate(item["id"], NOW)
    if mode == "manual":
        content.approve_candidate(OWNER, item["id"], checked["version"])
    return delivery.schedule(item["id"], NOW)


def test_confirmed_release_is_durable_and_repeated_trigger_cannot_send_twice():
    job = prepare()
    transport = Platform()
    assert delivery.run_one(transport, NOW)
    assert not delivery.run_one(transport, NOW + timedelta(hours=1))
    with store.connection() as c:
        saved = store.get(c, "delivery", job["id"])
        item = store.get(c, "candidate", job["candidate_id"])
        assert saved["status"] == item["status"] == "published"
        assert saved["external_id"] == "post-123"
    assert delivery.schedule(job["candidate_id"], NOW)["id"] == job["id"]
    assert len(transport.calls) == 1


def test_lost_response_is_unknown_and_never_retried_blindly():
    job = prepare()
    transport = Platform(TimeoutError("reply lost"))
    delivery.run_one(transport, NOW)
    assert not delivery.run_one(transport, NOW + timedelta(hours=2))
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "unknown"
    assert len(transport.calls) == 1


def test_explicit_transient_rejection_has_bounded_clock_based_retries():
    job = prepare()
    transport = Platform(delivery.TemporaryRejection("rate limited", retry_after=60))
    delivery.run_one(transport, NOW)
    assert not delivery.run_one(transport, NOW + timedelta(seconds=59))
    assert delivery.run_one(transport, NOW + timedelta(minutes=30))
    assert delivery.run_one(transport, NOW + timedelta(minutes=60))
    assert not delivery.run_one(transport, NOW + timedelta(minutes=90))
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "error"
    assert len(transport.calls) == 3


@pytest.mark.parametrize("action", ["pause", "revoke", "change_source", "revise", "cancel", "expiry"])
def test_preflight_rechecks_every_mutable_input(action):
    job = prepare()
    with store.connection() as c:
        a = store.get(c, "account", "tg")
        item = store.get(c, "candidate", job["candidate_id"])
        source = store.get(c, "evidence", "decision")
    if action == "pause":
        delivery.set_pause(OWNER, publications=True)
    elif action == "revoke":
        data = {key: a[key] for key in permissions.Account.model_fields}
        permissions.save_account(OWNER, "tg", {**data, "mode": "draft"}, a["version"])
    elif action == "change_source":
        data = {key: source[key] for key in content.Evidence.model_fields}
        content.save_evidence(OWNER, "decision", {**data, "data": {"dividend": 99}}, source["version"])
    elif action == "revise":
        content.revise_candidate(OWNER, item["id"], {"body": "Revised"}, item["version"])
    elif action == "cancel":
        content.cancel_candidate(OWNER, item["id"], item["version"])
    transport = Platform()
    delivery.run_one(transport, NOW + timedelta(days=2) if action == "expiry" else NOW)
    assert transport.calls == []
    if action == "cancel":
        with store.connection() as c:
            assert store.get(c, "delivery", job["id"])["status"] == "cancelled"


def test_release_window_and_interval_are_account_scoped():
    job = prepare()
    transport = Platform()
    assert not delivery.run_one(transport, NOW.replace(hour=0))
    assert delivery.run_one(transport, NOW)
    another = candidate("another")
    content.check_candidate(another["id"], NOW)
    delivery.schedule(another["id"], NOW)
    assert not delivery.run_one(transport, NOW + timedelta(minutes=29))
    assert delivery.run_one(transport, NOW + timedelta(minutes=30))
    assert len(transport.calls) == 2


@pytest.mark.parametrize("mode", ["automatic", "manual"])
def test_future_publication_time_survives_repeated_scheduling_and_worker_restart(mode):
    a = account(mode=mode)
    delivery.record_connection("tg", a["version"], external_id=a["external_id"], verified=True, now=NOW)
    evidence()
    due = NOW + timedelta(hours=1)
    item = candidate(mode=mode, not_before=due.astimezone(permissions.TASHKENT).isoformat())
    checked = content.check_candidate(item["id"], NOW)
    if mode == "manual":
        content.approve_candidate(OWNER, item["id"], checked["version"])
    first = delivery.schedule(item["id"], NOW)
    assert permissions.timestamp(first["next_attempt_at"]) == due
    assert delivery.schedule(item["id"], NOW + timedelta(minutes=1))["version"] == first["version"]
    from marketing import worker
    transport = Platform()
    assert not worker.tick(now=due - timedelta(seconds=1), transport=transport)["delivery_work"]
    assert worker.tick(now=due, transport=transport)["delivery_work"]
    assert not worker.tick(now=due + timedelta(minutes=30), transport=transport)["delivery_work"]
    assert len(transport.calls) == 1


@pytest.mark.parametrize("planned", ["2026-11-23T14:00:00", "2026-11-24T07:00:00Z", "2026-11-25T07:00:00Z"])
def test_future_time_requires_a_zone_and_precedes_content_expiry(planned):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        candidate(not_before=planned)


def test_existing_material_without_optional_schedule_can_be_edited():
    item = candidate(mode="manual")
    with store.connection(write=True) as c:
        old = {key: value for key, value in item.items() if key != "not_before"}
        old = store.put(c, "candidate", old, actor=OWNER, action="prior_schema_fixture", expected_version=item["version"])
    revised = content.revise_candidate(OWNER, old["id"], {"not_before": (NOW + timedelta(hours=1)).isoformat()}, old["version"])
    assert revised["not_before"] and revised["status"] == "draft"


def test_restart_recovers_inflight_as_unknown_without_repeating_send():
    job = prepare()
    with store.connection(write=True) as c:
        stored = store.get(c, "delivery", job["id"])
        store.put(c, "delivery", {**stored, "status": "sending", "claimed_at": NOW.isoformat()},
                  actor={"id": "worker"}, action="claim", expected_version=stored["version"])
    transport = Platform()
    assert delivery.recover_inflight(NOW + timedelta(minutes=10)) == 1
    assert not delivery.run_one(transport, NOW + timedelta(minutes=11))
    assert transport.calls == []
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "unknown"


def test_http_success_without_platform_post_id_is_not_publication():
    job = prepare()
    delivery.run_one(Platform({"ok": True}), NOW)
    with store.connection() as c:
        assert store.get(c, "delivery", job["id"])["status"] == "unknown"


def test_unrepresentable_retry_delay_stops_without_shortening_or_replaying_it():
    job = prepare()
    platform = Platform(delivery.TemporaryRejection("rate limited", retry_after=10 ** 30))
    assert delivery.run_one(platform, NOW)
    with store.connection() as c:
        saved = store.get(c, "delivery", job["id"])
        assert saved["status"] == "error" and "delay" in saved["reason"]
    assert not delivery.run_one(platform, NOW + timedelta(hours=1))
    assert len(platform.calls) == 1


def test_paid_content_cannot_enter_organic_queue():
    account()
    evidence()
    item = candidate(publication_type="paid")
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "draft"
    with pytest.raises(MarketingError):
        delivery.schedule(item["id"], NOW)


def test_revised_unsent_manual_material_can_be_reapproved_and_replaces_only_the_unsent_job():
    a = account(mode="manual")
    delivery.record_connection("tg", a["version"], external_id=a["external_id"], verified=True, now=NOW)
    evidence()
    item = candidate(mode="manual")
    checked = content.check_candidate(item["id"], NOW)
    content.approve_candidate(OWNER, item["id"], checked["version"])
    first = delivery.schedule(item["id"], NOW)
    with store.connection() as c:
        current = store.get(c, "candidate", item["id"])
    future = NOW + timedelta(hours=1)
    revised = content.revise_candidate(OWNER, item["id"], {"body": "Утверждено 120 сум на простую акцию. Новая подача.",
                                       "not_before": future.isoformat()}, current["version"])
    assert revised["approval"] is None and revised["check"] is None
    checked = content.check_candidate(item["id"], NOW)
    content.approve_candidate(OWNER, item["id"], checked["version"])
    second = delivery.schedule(item["id"], NOW)
    assert second["id"] == first["id"] and second["content_digest"] != first["content_digest"]
    assert permissions.timestamp(second["next_attempt_at"]) == future
    transport = Platform()
    assert not delivery.run_one(transport, NOW)
    assert delivery.run_one(transport, future)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("mode,status", [("automatic", "skipped"), ("manual", "needs_revision")])
def test_changed_original_finishes_automatic_release_but_allows_manual_reapproval(mode, status):
    job = prepare(mode)
    with store.connection() as c:
        source = store.get(c, "evidence", "decision")
    data = {key: source[key] for key in content.Evidence.model_fields}
    content.save_evidence(OWNER, "decision", {**data, "data": {**data["data"], "dividend": 99}}, source["version"])
    transport = Platform()
    assert not delivery.run_one(transport, NOW)
    with store.connection() as c:
        item = store.get(c, "candidate", job["candidate_id"])
        assert item["status"] == status
        assert not item["check"]["passed"]
        assert store.get(c, "delivery", job["id"])["status"] == "blocked"
    if mode == "automatic":
        assert candidate()["status"] == "skipped"
    else:
        content.revise_candidate(OWNER, item["id"], {"body": "Утверждено 99 сум на простую акцию.",
            "claims": [{"evidence_id": "decision", "field": "dividend", "value": 99, "unit": "UZS/share"}]}, item["version"])
        checked = content.check_candidate(item["id"], NOW)
        content.approve_candidate(OWNER, item["id"], checked["version"])
        delivery.schedule(item["id"], NOW)
        assert delivery.run_one(transport, NOW)
        assert len(transport.calls) == 1
