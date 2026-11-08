"""Collection execution must not be inferred from the age of a data row."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import pytest
from collection_ops import model, store

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)
JOB = "quotes-catchup"

def observation(**changes):
    return {"job": JOB, "invocation": "run-1", "started_at": "2026-11-07T09:58:00+00:00",
            "finished_at": "2026-11-07T09:59:00+00:00", "active": False,
            "load_state": "loaded", "result": "success", "exit_code": 0,
            "timer_enabled": True, "timer_active": True, "next_run": "2026-11-07T13:00:00+00:00",
            "evidence": "", "receipts": [], **changes}

@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    path = tmp_path / "operations.sqlite3"
    def connect():
        c = sqlite3.connect(path, timeout=10)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(store, "connect", connect)
    monkeypatch.setattr(store, "utcnow", lambda: NOW)
    return connect


def test_release_requires_new_reports_for_every_collector(isolated_store):
    from collection_ops.verify import require_fresh_reports
    from collection_ops.registry import JOBS

    since = NOW - timedelta(seconds=10)
    with pytest.raises(RuntimeError, match="offline"):
        require_fresh_reports(store.overview(), since)
    store.report([observation()])
    with pytest.raises(RuntimeError, match="collector"):
        require_fresh_reports(store.overview(), since)
    # A collector failure is useful evidence, not a failed monitor health check.
    store.report([observation(job=job, result="exit-code", exit_code=1) for job in JOBS])
    assert require_fresh_reports(store.overview(), since)["observed_jobs"] == len(JOBS)
    with pytest.raises(RuntimeError, match="before this check"):
        require_fresh_reports(store.overview(), NOW + timedelta(seconds=1))


@pytest.mark.parametrize("completes", [True, False])
def test_manual_verification_waits_for_one_real_request(isolated_store, monkeypatch, completes):
    from collection_ops import verify

    job = "bank-fx"
    store.report([observation(job=job)])
    delays = []

    def advance(seconds):
        delays.append(seconds)
        if completes:
            request = store.claim()
            assert request["actor_id"] == 0  # Server operator, never impersonate an admin user.
            store.ack(request["id"], "dispatched", "manual-bank-fx")
            store.report([observation(job=job, invocation="manual-bank-fx", receipts=[
                {"stage": "/api/admin/bank-fx", "ok": True, "counts": {"upserted": 12}}])])

    monkeypatch.setattr(verify.time, "sleep", advance)
    monkeypatch.setattr(verify.time, "monotonic", lambda: sum(delays))
    if completes:
        result = verify.exercise_manual_run(store, job, timeout=10)
        assert result["status"] == "completed"
        assert result["publication"] == "acknowledged"
        assert delays == [5]
    else:
        with pytest.raises(RuntimeError, match="not confirmed"):
            verify.exercise_manual_run(store, job, timeout=10)
        assert delays == [5, 5]
    current = next(x for x in store.overview()["items"] if x["id"] == job)
    assert len(current["requests"]) == 1

@pytest.mark.parametrize("result,code,expected", [
    ("timeout", None, "timeout"), ("oom-kill", 137, "memory_limit"),
    ("exit-code", 1, "failed"), ("signal", 9, "terminated"),
])
def test_system_failure_is_visible_even_without_collector_logs(result, code, expected):
    run = model.outcome(observation(result=result, exit_code=code))
    assert run["status"] == "failed"
    assert run["reason_code"] == expected
    assert run["reason"]

def test_successful_exit_does_not_prove_that_publication_happened():
    run = model.outcome(observation())
    assert run["status"] == "completed"
    assert run["publication"] == "unverified"
    assert model.outcome(observation(active=True))["status"] == "running"

def test_partial_delivery_is_not_reported_as_success_even_when_process_exits_zero():
    run = model.outcome(observation(receipts=[
        {"stage": "/api/admin/quotes", "ok": True, "counts": {"upserted": 123}},
        {"stage": "/api/admin/trade-stats", "ok": False, "reason": "HTTP 503"},
    ]))
    assert run["status"] == "partial"
    assert run["failed_stage"] == "/api/admin/trade-stats"
    assert "HTTP 503" in run["reason"]

def test_explicit_no_change_and_acknowledged_writes_are_distinct():
    quiet = model.outcome(observation(receipts=[{"stage": "quotes", "ok": True,
        "unchanged": True, "reason": "Production already has source session 2026-11-06"}]))
    assert quiet["status"] == "no_change"
    assert "2026-11-06" in quiet["reason"]
    accepted = model.outcome(observation(receipts=[{"stage": "/api/admin/quotes", "ok": True,
        "counts": {"upserted": 123}}]))
    assert accepted["publication"] == "acknowledged"
    assert accepted["status"] == "completed"  # Upserts are not necessarily changed prices.

def test_redaction_happens_before_logs_are_stored(monkeypatch, isolated_store):
    monkeypatch.setenv("ADMIN_API_SECRET", "s3cret")
    monkeypatch.setenv("DEPLOY_SSH_HOST", "private-host.example")
    store.report([observation(evidence="Authorization: Bearer abcdef\npassword=abc123 "
        "https://joe:pw@example.com/x?token=qqq s3cret private-host.example")])
    data = json.dumps(store.overview())
    for secret in ("abcdef", "abc123", "joe:pw", "qqq", "s3cret", "private-host.example"):
        assert secret not in data

def test_history_survives_restart_and_repeated_observation_does_not_duplicate(isolated_store):
    store.report([observation()])
    store.report([observation()])
    store.report([observation(invocation="run-2", result="timeout", exit_code=None)])
    job = next(x for x in store.overview()["items"] if x["id"] == JOB)
    assert len(job["history"]) == 2
    assert job["latest"]["reason_code"] == "timeout"

def test_manual_request_is_durable_deduplicated_and_claimed_once(isolated_store):
    store.report([observation()])
    request = store.enqueue(JOB, actor_id=41)
    assert store.enqueue(JOB, actor_id=41)["id"] == request["id"]
    assert store.claim()["id"] == request["id"]
    assert store.claim() is None
    store.ack(request["id"], "dispatched", "run-2", "Started by systemd")
    store.report([observation()])  # The old invocation cannot unlock the new request.
    assert store.enqueue(JOB, actor_id=41)["id"] == request["id"]
    store.report([observation(invocation="run-2")])
    assert store.enqueue(JOB, actor_id=41)["id"] != request["id"]

def test_stale_monitor_or_active_service_cannot_queue_a_run(isolated_store, monkeypatch):
    with pytest.raises(store.OperationError, match="monitor"):
        store.enqueue(JOB, actor_id=41)
    store.report([observation(active=True)])
    with pytest.raises(store.OperationError, match="running"):
        store.enqueue(JOB, actor_id=41)
    store.report([observation()])
    monkeypatch.setattr(store, "utcnow", lambda: NOW + timedelta(minutes=4))
    with pytest.raises(store.OperationError, match="monitor"):
        store.enqueue(JOB, actor_id=41)

def test_lost_dispatch_ack_is_uncertain_and_never_retried_automatically(isolated_store, monkeypatch):
    store.report([observation()])
    request = store.enqueue(JOB, actor_id=41)
    store.claim()
    monkeypatch.setattr(store, "utcnow", lambda: NOW + timedelta(minutes=4))
    store.report([observation()])
    assert store.claim() is None
    job = next(x for x in store.overview()["items"] if x["id"] == JOB)
    assert job["request"]["status"] == "uncertain"
    assert store.enqueue(JOB, actor_id=41)["id"] == request["id"]
    store.release(request["id"], actor_id=41)
    assert store.enqueue(JOB, actor_id=41)["id"] != request["id"]

def test_commands_are_allowlisted_and_timer_failure_is_separate_from_last_run(isolated_store):
    with pytest.raises(store.OperationError):
        store.enqueue("quotes-catchup; reboot", actor_id=41)
    store.report([observation(timer_enabled=False, timer_active=False)])
    job = next(x for x in store.overview()["items"] if x["id"] == JOB)
    assert job["schedule_issue"] == "timer_disabled"
    assert job["latest"]["status"] == "completed"
    assert job["run_command"] == "sudo systemctl start --no-block uzstock-quotes-catchup.service"

def test_history_list_is_small_and_full_log_is_loaded_on_demand(isolated_store):
    store.report([observation(evidence="an exact recorded error")])
    job = next(x for x in store.overview()["items"] if x["id"] == JOB)
    assert "evidence" not in job["history"][0]
    assert store.read_run(JOB, "run-1")["evidence"] == "an exact recorded error"

def test_missed_scheduled_start_is_detected_from_previous_timer_observation(isolated_store, monkeypatch):
    store.report([observation(next_run="2026-11-07T10:01:00+00:00")])
    monkeypatch.setattr(store, "utcnow", lambda: NOW + timedelta(minutes=4))
    store.report([observation(next_run="2026-11-07T13:00:00+00:00")])
    job = next(x for x in store.overview()["items"] if x["id"] == JOB)
    assert job["schedule_issue"] == "missed_schedule"
    store.report([observation(invocation="run-2", next_run="2026-11-07T13:00:00+00:00")])
    job = next(x for x in store.overview()["items"] if x["id"] == JOB)
    assert job["schedule_issue"] is None

def test_redaction_cannot_break_structured_observations(isolated_store):
    store.report([observation(evidence='Authorization: Bearer abcdef')])
    assert 'abcdef' not in store.read_run(JOB, 'run-1')["evidence"]

def test_lost_dispatched_invocation_does_not_leave_a_permanent_lock(isolated_store, monkeypatch):
    store.report([observation()])
    request = store.enqueue(JOB, actor_id=41)
    store.claim()
    store.ack(request["id"], "dispatched", "run-2", "Accepted")
    monkeypatch.setattr(store, "utcnow", lambda: NOW + timedelta(minutes=4))
    store.report([observation(invocation="")])
    job = next(x for x in store.overview()["items"] if x["id"] == JOB)
    assert job["request"]["status"] == "uncertain"

def test_two_simultaneous_clicks_produce_one_request_and_one_claim(isolated_store):
    from concurrent.futures import ThreadPoolExecutor
    store.report([observation()])
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = list(pool.map(lambda _: store.enqueue(JOB, actor_id=41), range(2)))
        claims = list(pool.map(lambda _: store.claim(), range(2)))
    assert len({request['id'] for request in requests}) == 1
    assert sum(claim is not None for claim in claims) == 1

def test_earlier_publication_failure_survives_later_log_tail_observations(isolated_store):
    store.report([observation(active=True, receipts=[
        {"stage": "quote_history", "ok": False, "reason": "History store unavailable"}])])
    store.report([observation(receipts=[{"stage": "/api/admin/quotes", "ok": True,
                                         "counts": {"upserted": 5}}])])
    result = store.read_run(JOB, "run-1")
    assert result["status"] == "partial"
    assert result["failed_stage"] == "quote_history"

def test_heartbeat_receipt_does_not_hide_no_change_or_become_a_data_write():
    result = model.outcome(observation(receipts=[
        {"stage": "openinfo/session", "ok": True, "unchanged": True, "reason": "Session already published."},
        {"stage": "heartbeat", "ok": True, "counts": {"upserted": 2}},
    ]))
    assert result["status"] == "no_change"
    assert result["publication"] == "unverified"

def test_checked_and_rejected_counts_are_not_confirmed_writes():
    result = model.outcome(observation(receipts=[{"stage": "financials", "ok": True,
        "counts": {"checked": 10, "rejected": 10, "upserted": 0}}]))
    assert result["publication"] == "unverified"

def test_a_run_overlapping_its_next_schedule_is_not_misreported_as_a_missed_start(isolated_store, monkeypatch):
    store.report([observation(job="financial-ingestion", active=True, next_run="2026-11-07T10:01:00+00:00")])
    monkeypatch.setattr(store, "utcnow", lambda: NOW + timedelta(minutes=4))
    store.report([observation(job="financial-ingestion", active=False, next_run="2026-11-08T10:01:00+00:00")])
    job = next(x for x in store.overview()["items"] if x["id"] == "financial-ingestion")
    assert job["schedule_issue"] is None
