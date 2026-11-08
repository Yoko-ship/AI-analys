"""Durable observations and a dispatch queue, serialized in the database."""
from contextlib import contextmanager
from datetime import timedelta
import json
import uuid

import dbx
from catalogue.storage import get_catalog_conn as connect
from collection_ops.model import outcome, parse_time, scrub, utcnow
from collection_ops.registry import JOBS, canonical_id, related_ids

FRESH_SECONDS = 180

class OperationError(Exception):
    pass

def _schema(c):
    c.executescript("""
        CREATE TABLE IF NOT EXISTS collection_control (id INTEGER PRIMARY KEY, touched_at TEXT NOT NULL);
        INSERT INTO collection_control(id,touched_at) VALUES(1,'') ON CONFLICT(id) DO NOTHING;
        CREATE TABLE IF NOT EXISTS collection_observations (
          job TEXT PRIMARY KEY, observed_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS collection_runs (
          job TEXT NOT NULL, invocation TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY(job,invocation));
        CREATE TABLE IF NOT EXISTS collection_requests (
          id TEXT PRIMARY KEY, job TEXT NOT NULL, status TEXT NOT NULL, actor_id INTEGER NOT NULL,
          requested_at TEXT NOT NULL, claimed_at TEXT, finished_at TEXT, invocation TEXT,
          detail TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS collection_request_time ON collection_requests(requested_at);
        CREATE TABLE IF NOT EXISTS collection_locks (job TEXT PRIMARY KEY, request_id TEXT NOT NULL);
    """)
    c.commit()

@contextmanager
def _db():
    c = connect()
    try:
        dbx.ensure_schema(c, "collection-operations-v1", _schema)
        # A row lock works for PostgreSQL; SQLite serializes the write transaction.
        # This covers concurrent API workers and the observer, not just one process.
        c.execute("UPDATE collection_control SET touched_at=? WHERE id=1", (utcnow().isoformat(),))
        _expire(c)
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def _expire(c):
    stamp = utcnow()
    c.execute("UPDATE collection_requests SET status='uncertain', detail=? WHERE status='dispatching' AND claimed_at<?",
              ("The server did not confirm dispatch. Check the service before clearing this request.",
               (stamp - timedelta(seconds=FRESH_SECONDS)).isoformat()))
    expired = c.execute("SELECT id FROM collection_requests WHERE status='queued' AND requested_at<?",
                        ((stamp - timedelta(minutes=15)).isoformat(),)).fetchall()
    for row in expired:
        _finish(c, row["id"], "expired", "The monitor did not pick up this request within 15 minutes.")

def _finish(c, request_id, status, detail):
    c.execute("UPDATE collection_requests SET status=?, detail=?, finished_at=? WHERE id=?",
              (status, scrub(detail)[:2000], utcnow().isoformat(), request_id))
    c.execute("DELETE FROM collection_locks WHERE request_id=?", (request_id,))

def _job(job):
    job = canonical_id(job)
    if job not in JOBS:
        raise OperationError("Unknown collector.")
    return JOBS[job]

def _observation(c, job):
    row = c.execute("SELECT observed_at,payload FROM collection_observations WHERE job=?", (job,)).fetchone()
    if not row:
        return None, None
    return row["observed_at"], outcome(json.loads(row["payload"]))

def _fresh(stamp):
    time = parse_time(stamp)
    return time is not None and 0 <= (utcnow() - time).total_seconds() < FRESH_SECONDS

def _pending(c, job):
    family = related_ids(job)
    row = c.execute("SELECT r.* FROM collection_requests r JOIN collection_locks l ON l.request_id=r.id "
                    "WHERE l.job IN (" + ",".join("?" for _ in family) + ") "
                    "ORDER BY CASE WHEN r.status='queued' THEN 1 ELSE 0 END,r.requested_at,r.id LIMIT 1", family).fetchone()
    return dict(row) if row else None

def report(observations):
    with _db() as c:
        now = utcnow().isoformat()
        for raw in observations:
            job = raw["job"]
            _job(job)
            value = outcome(raw)
            _, previous = _observation(c, job)
            if previous and previous.get("invocation") == value.get("invocation"):
                # Polls read a bounded journal tail. Preserve receipts already seen
                # in this invocation, especially a failure before later chatter.
                events = {}
                for event in (previous.get("receipts") or []) + (value.get("receipts") or []):
                    key = event.get("event_id") or json.dumps(event, sort_keys=True)
                    events[key] = event
                receipts = list(events.values())
                if len(receipts) > 100:
                    failed = [r for r in receipts if r.get("ok") is False][-20:]
                    successful = [r for r in receipts if r.get("ok") is not False][-(100-len(failed)):]
                    receipts = successful + failed
                    value["evidence_truncated"] = True
                value = outcome({**value, "receipts": receipts})
            if previous and previous.get("invocation") == value.get("invocation") and not previous.get("active") and not value.get("active"):
                due = parse_time(previous.get("next_run"))
                if previous.get("missed_schedule") or (due and utcnow() > due + timedelta(seconds=90)):
                    value["missed_schedule"] = True
            payload = json.dumps(value, ensure_ascii=False)
            c.execute("INSERT INTO collection_observations(job,observed_at,payload) VALUES(?,?,?) "
                      "ON CONFLICT(job) DO UPDATE SET observed_at=excluded.observed_at,payload=excluded.payload",
                      (job, now, payload))
            if value.get("invocation"):
                c.execute("INSERT INTO collection_runs(job,invocation,observed_at,payload) VALUES(?,?,?,?) "
                          "ON CONFLICT(job,invocation) DO UPDATE SET observed_at=excluded.observed_at,payload=excluded.payload",
                          (job, value["invocation"], now, payload))
                c.execute("DELETE FROM collection_runs WHERE job=? AND invocation NOT IN "
                          "(SELECT invocation FROM collection_runs WHERE job=? ORDER BY observed_at DESC,invocation DESC LIMIT 50)", (job, job))
            pending = _pending(c, job)
            if pending and pending["status"] == "dispatched" and pending["invocation"] == value.get("invocation") and not value.get("active"):
                _finish(c, pending["id"], "finished", value["reason"])
            elif pending and pending["status"] == "dispatched" and pending["invocation"] != value.get("invocation") and not value.get("active"):
                claimed = parse_time(pending["claimed_at"])
                if claimed and utcnow() > claimed + timedelta(seconds=FRESH_SECONDS):
                    c.execute("UPDATE collection_requests SET status='uncertain',detail=? WHERE id=?",
                              ("The accepted invocation is no longer observable. Check the journal before clearing this request.", pending["id"]))
        # Retain request audit history for 90 days, never prune active requests.
        c.execute("DELETE FROM collection_requests WHERE finished_at IS NOT NULL AND finished_at<?",
                  ((utcnow() - timedelta(days=90)).isoformat(),))
    return {"ok": True}

def overview():
    with _db() as c:
        items, stamps = [], []
        for job in JOBS.values():
            family = related_ids(job.id)
            placeholders = ",".join("?" for _ in family)
            stamp, latest = _observation(c, job.id)
            if stamp:
                stamps.append(stamp)
            latest = latest or outcome({})
            pending = _pending(c, job.id)
            issue = ("monitor_offline" if not _fresh(stamp) else
                     "service_missing" if latest.get("load_state") != "loaded" else
                     "timer_disabled" if not latest.get("timer_enabled") else
                     "timer_inactive" if not latest.get("timer_active") else
                     "missed_schedule" if latest.get("missed_schedule") else None)
            history = [{k: v for k, v in outcome(json.loads(r["payload"])).items() if k not in ("evidence", "receipts")} for r in c.execute(
                f"SELECT payload FROM collection_runs WHERE job IN ({placeholders}) ORDER BY observed_at DESC,job,invocation DESC LIMIT 10", family).fetchall()]
            requests = [dict(r) for r in c.execute(
                f"SELECT * FROM collection_requests WHERE job IN ({placeholders}) ORDER BY requested_at DESC,id DESC LIMIT 10", family).fetchall()]
            items.append({**job.public(), "latest": latest, "history": history, "requests": requests,
                          "request": pending, "observed_at": stamp, "next_run": latest.get("next_run"),
                          "schedule_issue": issue,
                          "can_run": _fresh(stamp) and latest.get("load_state") == "loaded" and not latest.get("active") and not pending})
        last_seen = max(stamps) if stamps else None
        return {"observer": {"last_seen": last_seen, "online": _fresh(last_seen)},
                "timezone": "Asia/Tashkent", "items": items}

def read_run(job, invocation):
    _job(job)
    with _db() as c:
        row = c.execute("SELECT payload FROM collection_runs WHERE job=? AND invocation=?", (job, invocation)).fetchone()
        if not row and canonical_id(job) != job:
            row = c.execute("SELECT payload FROM collection_runs WHERE job=? AND invocation=?", (canonical_id(job), invocation)).fetchone()
        if not row:
            raise OperationError("This run is no longer in the retained history.")
        return outcome(json.loads(row["payload"]))

def enqueue(job, *, actor_id):
    job = _job(job).id
    with _db() as c:
        pending = _pending(c, job)
        if pending:
            return pending
        stamp, latest = _observation(c, job)
        if not _fresh(stamp):
            raise OperationError("The server monitor is offline. Use the server command or restore monitoring.")
        if latest.get("load_state") != "loaded":
            raise OperationError("The service is not installed on the server.")
        if latest.get("active"):
            raise OperationError("This collector is already running.")
        request_id = uuid.uuid4().hex
        c.execute("INSERT INTO collection_requests(id,job,status,actor_id,requested_at,detail) VALUES(?,?,'queued',?,?,?)",
                  (request_id, job, actor_id, utcnow().isoformat(), "Waiting for the server monitor."))
        c.execute("INSERT INTO collection_locks(job,request_id) VALUES(?,?)", (job, request_id))
        return dict(c.execute("SELECT * FROM collection_requests WHERE id=?", (request_id,)).fetchone())

def claim():
    with _db() as c:
        rows = c.execute("SELECT * FROM collection_requests WHERE status='queued' ORDER BY requested_at,id").fetchall()
        for row in rows:
            # Requests queued against different retired schedules now share one
            # worker. Wait for its current request, without blocking other jobs.
            pending = _pending(c, row["job"])
            if not pending or pending["id"] != row["id"]:
                continue
            c.execute("UPDATE collection_requests SET status='dispatching',claimed_at=? WHERE id=?",
                      (utcnow().isoformat(), row["id"]))
            return {**dict(row), "job": canonical_id(row["job"]), "status": "dispatching"}
        return None

def ack(request_id, status, invocation="", detail=""):
    if status not in ("dispatched", "failed", "uncertain"):
        raise OperationError("Invalid dispatch result.")
    with _db() as c:
        row = c.execute("SELECT * FROM collection_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise OperationError("Unknown request.")
        if row["status"] not in ("dispatching", "uncertain"):
            return {"ok": True}  # Idempotent replay of the host outbox.
        if status == "dispatched" and not invocation:
            raise OperationError("A dispatch must identify its service invocation.")
        if status == "failed":
            _finish(c, request_id, status, detail)
        else:
            c.execute("UPDATE collection_requests SET status=?,invocation=?,detail=? WHERE id=?",
                      (status, invocation, scrub(detail)[:2000], request_id))
    return {"ok": True}

def release(request_id, *, actor_id):
    with _db() as c:
        row = c.execute("SELECT * FROM collection_requests WHERE id=?", (request_id,)).fetchone()
        if not row or row["status"] not in ("queued", "uncertain"):
            raise OperationError("Only queued or uncertain requests can be cleared.")
        stamp, latest = _observation(c, canonical_id(row["job"]))
        if not _fresh(stamp) or latest.get("active"):
            raise OperationError("Wait for a fresh monitor report confirming that the service is not running.")
        _finish(c, request_id, "cleared", f"Cleared by administrator {actor_id}; this does not stop a service.")
    return {"ok": True}
