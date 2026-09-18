"""Persistent jobs, immutable evidence and atomic publication pointers.

Uses the existing catalog database, not a second service or an ephemeral queue.
Money is stored as decimal strings in candidate/snapshot JSON, never floats.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import time
from uuid import uuid4

import dbx


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS ingest_sources (
      id TEXT PRIMARY KEY, org_id TEXT NOT NULL, ticker TEXT NOT NULL,
      url TEXT NOT NULL, category TEXT NOT NULL, metadata_json TEXT NOT NULL,
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      checked_at REAL, latest_version TEXT, UNIQUE(org_id,url)
    );
    CREATE TABLE IF NOT EXISTS ingest_artifacts (
      sha TEXT PRIMARY KEY, relative_path TEXT NOT NULL, byte_count INTEGER NOT NULL,
      media_type TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ingest_versions (
      id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES ingest_sources(id),
      sha TEXT NOT NULL REFERENCES ingest_artifacts(sha), metadata_json TEXT NOT NULL,
      received_at TEXT NOT NULL, UNIQUE(source_id,sha)
    );
    CREATE TABLE IF NOT EXISTS ingest_jobs (
      id TEXT PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE,
      source_id TEXT NOT NULL REFERENCES ingest_sources(id), version_id TEXT,
      stage TEXT NOT NULL, processor TEXT NOT NULL, state TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL,
      lease_until REAL, lease_token TEXT, error TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ingest_jobs_due ON ingest_jobs(state,available_at);
    CREATE TABLE IF NOT EXISTS ingest_candidates (
      id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES ingest_versions(id),
      processor TEXT NOT NULL, payload_json TEXT NOT NULL,
      checks_json TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ingest_reviews (
      id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES ingest_candidates(id),
      actor TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
      created_at TEXT NOT NULL, UNIQUE(candidate_id,decision,actor,reason)
    );
    CREATE TABLE IF NOT EXISTS ingest_snapshots (
      id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES ingest_candidates(id),
      review_id TEXT NOT NULL REFERENCES ingest_reviews(id),
      org_id TEXT NOT NULL, standard TEXT NOT NULL, scope TEXT NOT NULL,
      period_start TEXT NOT NULL, period_end TEXT NOT NULL,
      payload_json TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ingest_heads (
      org_id TEXT NOT NULL, standard TEXT NOT NULL, scope TEXT NOT NULL,
      period_start TEXT NOT NULL, period_end TEXT NOT NULL,
      snapshot_id TEXT NOT NULL REFERENCES ingest_snapshots(id),
      PRIMARY KEY(org_id,standard,scope,period_start,period_end)
    );
    CREATE TABLE IF NOT EXISTS ingest_events (
      id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, action TEXT NOT NULL,
      actor TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL
    );
    """)
    c.commit()


def connect():
    from reports_catalog import get_catalog_conn
    c = get_catalog_conn()
    dbx.ensure_schema(c, "financial-ingestion-v1", _schema)
    return c


@contextmanager
def transaction():
    c = connect()
    try:
        # Serialize SQLite writers; readers retain the previous WAL snapshot.
        c.execute("BEGIN IMMEDIATE" if dbx.backend() == dbx.SQLITE else "BEGIN")
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def event(c, entity_id, action, actor="worker", **detail):
    c.execute("INSERT INTO ingest_events VALUES (?,?,?,?,?,?)",
              (uuid4().hex, entity_id, action, actor, encoded(detail), now()))


def enqueue(c, source_id, stage, processor, *, version_id=None, generation="initial"):
    key = digest([source_id, stage, processor, version_id, generation])
    c.execute("INSERT INTO ingest_jobs (id,dedupe_key,source_id,version_id,stage,processor,state,"
              "available_at,created_at,updated_at) VALUES (?,?,?,?,?,?,'QUEUED',?,?,?) "
              "ON CONFLICT(dedupe_key) DO NOTHING",
              (key, key, source_id, version_id, stage, processor, time.time(), now(), now()))
    return key


def claim(*, lease_seconds=900, max_attempts=3, stages=("FETCH", "EXTRACT")):
    clock = time.time()
    with transaction() as c:
        # A killed worker cannot own a job indefinitely, or publish after its
        # replacement. Tokens are checked again when results are committed.
        c.execute("UPDATE ingest_jobs SET state=CASE WHEN attempts>=? THEN 'FAILED' ELSE 'RETRY' END, "
                  "lease_token=NULL,lease_until=NULL,error='Worker lease expired',updated_at=? "
                  "WHERE state='RUNNING' AND lease_until<?", (max_attempts, now(), clock))
        marks = ",".join("?" for _ in stages)
        row = c.execute(f"SELECT * FROM ingest_jobs WHERE state IN ('QUEUED','RETRY') "
                        f"AND available_at<=? AND stage IN ({marks}) ORDER BY available_at,id LIMIT 1",
                        (clock, *stages)).fetchone()
        if not row:
            return None
        token = uuid4().hex
        updated = c.execute("UPDATE ingest_jobs SET state='RUNNING',attempts=attempts+1,"
                            "lease_token=?,lease_until=?,updated_at=? WHERE id=? AND state IN ('QUEUED','RETRY')",
                            (token, clock + lease_seconds, now(), row["id"]))
        if updated.rowcount != 1:
            return None
        event(c, row["id"], "job.claimed", attempt=row["attempts"] + 1)
        return {**dict(row), "lease_token": token, "attempts": row["attempts"] + 1}


def assert_lease(c, job):
    row = c.execute("SELECT state,lease_token,lease_until FROM ingest_jobs WHERE id=?", (job["id"],)).fetchone()
    if not row or row["state"] != "RUNNING" or row["lease_token"] != job["lease_token"] or row["lease_until"] < time.time():
        raise ValueError("Worker no longer owns this job")


def finish(c, job, state, error=None):
    assert_lease(c, job)
    c.execute("UPDATE ingest_jobs SET state=?,error=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?",
              (state, error, now(), job["id"]))
    event(c, job["id"], "job." + state.lower(), reason=error)


def fail(job, error, *, max_attempts=3):
    with transaction() as c:
        state = "FAILED" if job["attempts"] >= max_attempts else "RETRY"
        finish(c, job, state, str(error)[:1000])
        c.execute("UPDATE ingest_jobs SET available_at=? WHERE id=?",
                  (time.time() + min(3600, 60 * 2 ** (job["attempts"] - 1)), job["id"]))


def status(org_id=None):
    c = connect()
    try:
        where, args = (" WHERE s.org_id=?", (str(org_id),)) if org_id is not None else ("", ())
        sources = c.execute("SELECT s.* FROM ingest_sources s" + where, args).fetchall()
        jobs = c.execute("SELECT j.* FROM ingest_jobs j JOIN ingest_sources s ON s.id=j.source_id" + where, args).fetchall()
        counts = {}
        for row in jobs:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        heads = c.execute("SELECT COUNT(*) FROM ingest_heads" + (" WHERE org_id=?" if org_id is not None else ""), args).fetchone()[0]
        reviews = c.execute("SELECT DISTINCT v.source_id FROM ingest_candidates x JOIN ingest_versions v ON v.id=x.version_id "
                            "JOIN ingest_sources s ON s.id=v.source_id LEFT JOIN ingest_reviews r ON r.candidate_id=x.id "
                            + where + (" AND " if where else " WHERE ") + "r.id IS NULL AND s.latest_version=v.id "
                            "AND NOT EXISTS (SELECT 1 FROM ingest_candidates y JOIN ingest_reviews a ON a.candidate_id=y.id "
                            "WHERE y.version_id=v.id AND a.decision='APPROVED')", args).fetchall()
        pending = counts.get("QUEUED", 0) + counts.get("RETRY", 0) + counts.get("RUNNING", 0)
        stale = c.execute("SELECT COUNT(DISTINCT h.snapshot_id) FROM ingest_heads h "
                          "JOIN ingest_snapshots p ON p.id=h.snapshot_id JOIN ingest_candidates x ON x.id=p.candidate_id "
                          "JOIN ingest_versions v ON v.id=x.version_id JOIN ingest_sources s ON s.id=v.source_id "
                          "WHERE s.latest_version<>v.id" + (" AND s.org_id=?" if org_id is not None else ""), args).fetchone()[0]
        unpublished = c.execute("SELECT COUNT(DISTINCT x.id) FROM ingest_candidates x "
                                "JOIN ingest_reviews r ON r.candidate_id=x.id AND r.decision='APPROVED' "
                                "JOIN ingest_versions v ON v.id=x.version_id JOIN ingest_sources s ON s.id=v.source_id "
                                + where + (" AND " if where else " WHERE ") + "s.latest_version=v.id "
                                "AND NOT EXISTS (SELECT 1 FROM ingest_snapshots p WHERE p.candidate_id=x.id)", args).fetchone()[0]
        overdue = sum(not r["checked_at"] or r["checked_at"] < time.time() - 8 * 86400 for r in sources)
        return {"sources": len(sources), "jobs": counts, "published_periods": heads,
                "unreviewed_sources": len(reviews), "pending_jobs": pending, "stale_publications": stale,
                "approved_unpublished": unpublished, "overdue_sources": overdue,
                "last_checked_at": max((r["checked_at"] or 0 for r in sources), default=0),
                "status": "NO_SOURCES" if not sources else "PARTIAL" if pending or reviews or stale or unpublished or overdue or counts.get("FAILED") else "PROCESSED",
                "failures": [{"job_id": j["id"], "reason": j["error"]} for j in jobs if j["state"] == "FAILED"][:20]}
    finally:
        c.close()


def public_status(ticker):
    """Read-only until ingestion has been initialized; omit internal errors."""
    from reports_catalog import get_catalog_conn
    c = get_catalog_conn()
    try:
        if "ingest_sources" not in dbx.tables(c):
            return {"status": "NOT_INITIALIZED"}
        issuer = c.execute("SELECT org_id FROM catalog_companies WHERE ticker=?", (ticker.upper(),)).fetchone()
    finally:
        c.close()
    if not issuer or not issuer["org_id"]:
        return {"status": "NO_SOURCES"}
    result = status(issuer["org_id"])
    result.pop("failures", None)
    return result
