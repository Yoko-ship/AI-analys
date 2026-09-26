"""Idempotent analysis publications and exception queue; never edits a fact."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import dbx
from db import APP_DATA_DIR

from financial_analysis.sector_templates import VERSION
from financial_analysis.sector_numbers import digest
from financial_analysis.sector_language import tr


def connect():
    path = Path(os.getenv("SECTOR_ANALYSIS_DB") or APP_DATA_DIR / "sector_analysis.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = dbx.connect(str(path))
    dbx.ensure_schema(connection, "sector-analysis-v2.2", _create_schema)
    return connection


def _create_schema(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS sector_runs (
            version TEXT PRIMARY KEY, issuer_id TEXT NOT NULL, ticker TEXT NOT NULL,
            language TEXT NOT NULL, standard TEXT NOT NULL, period TEXT, status TEXT NOT NULL,
            created_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS sector_runs_issuer ON sector_runs(issuer_id, language, created_at);
        CREATE TABLE IF NOT EXISTS sector_publications (
            issuer_id TEXT, language TEXT, standard TEXT, version TEXT NOT NULL,
            PRIMARY KEY(issuer_id, language, standard));
        CREATE TABLE IF NOT EXISTS sector_jobs (
            id TEXT PRIMARY KEY, ticker TEXT NOT NULL, source_event TEXT NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt TEXT NOT NULL, error_code TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sector_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
            entity TEXT NOT NULL, old_value TEXT, new_value TEXT, reason TEXT NOT NULL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sector_overrides (
            version TEXT PRIMARY KEY, issuer_id TEXT NOT NULL, ticker TEXT NOT NULL,
            valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS sector_overrides_issuer ON sector_overrides(issuer_id, created_at);
        CREATE TABLE IF NOT EXISTS sector_publication_holds (
            issuer_id TEXT, language TEXT, standard TEXT, version TEXT, rejected_identity TEXT,
            PRIMARY KEY(issuer_id, language, standard));
    """)
    connection.commit()


def now():
    return datetime.now(timezone.utc).isoformat()


def publication_version(report):
    issuer = report.get("issuer") or {}
    with connect() as connection:
        row = connection.execute(
            "SELECT version FROM sector_publications WHERE issuer_id=? AND language=? AND standard=?",
            (str(issuer["id"]), report["language"], report["standard"]),
        ).fetchone()
    return row["version"] if row else None


def due_jobs(limit=10):
    """Activate rules, recover expired leases and return a bounded due batch."""
    stamp = now()
    with connect() as connection:
        rules = connection.execute(
            "SELECT version,ticker FROM sector_overrides WHERE valid_from<=? AND valid_to>=?",
            (stamp[:10], stamp[:10]),
        ).fetchall()
    for rule in rules:
        enqueue(rule["ticker"], "rule:" + rule["version"])
    with connect() as connection:
        expired = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        connection.execute("UPDATE sector_jobs SET state='queued' WHERE state='running' AND updated_at<?", (expired,))
        return [dict(row) for row in connection.execute(
            "SELECT * FROM sector_jobs WHERE state IN ('queued','retry') AND next_attempt<=? ORDER BY next_attempt LIMIT ?",
            (stamp, limit),
        ).fetchall()]


def claim_job(job_id):
    with connect() as connection:
        return bool(connection.execute(
            "UPDATE sector_jobs SET state='running',updated_at=? WHERE id=? AND state IN ('queued','retry')",
            (now(), job_id),
        ).rowcount)


def finish_job(job_id, state, attempts, error):
    next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=60 * 2 ** attempts)).isoformat()
    with connect() as connection:
        connection.execute(
            "UPDATE sector_jobs SET state=?,attempts=?,next_attempt=?,error_code=?,updated_at=? WHERE id=?",
            (state, attempts, next_attempt, error, now(), job_id),
        )


def record_report(report):
    key = (str(report["issuer"]["id"]), report["language"], report["standard"])
    with connect() as connection:
        hold = connection.execute("SELECT * FROM sector_publication_holds WHERE issuer_id=? AND language=? AND standard=?", key).fetchone()
        if hold:
            identity = digest([report.get("source_snapshot_hash"), report.get("template_resolution"), report.get("calculation_version")])
            if identity == hold["rejected_identity"]:
                row = connection.execute("SELECT payload FROM sector_runs WHERE version=?", (hold["version"],)).fetchone()
                restored = json.loads(row["payload"])
                restored["publication_restored"] = True
                restored["instrument"] = report.get("instrument")
                restored["market_as_of"] = report.get("market_as_of")
                restored["availability"]["next_action"] = "Restored publication; automatic replacement resumes after a source or rule update."
                checked_on = date.fromisoformat((report.get("generated_at") or now())[:10])
                financial_on = date.fromisoformat(restored["financial_as_of"])
                if (checked_on - financial_on).days > (550 if restored["standard"] == "ifrs" else 210):
                    restored["last_successful_report"] = {k: restored.get(k) for k in
                        ("version", "period", "financial_as_of", "generated_at", "headline", "paragraphs", "sources")}
                    restored["status"] = "stale"
                    restored["availability"]["reason_code"] = "stale"
                    restored["short_summary"] = None
                    restored["headline"] = tr(restored["language"], "Восстановленный отчёт устарел", "Tiklangan hisobot eskirgan", "The restored report is stale") + ": " + restored["period"]
                return restored
            connection.execute("DELETE FROM sector_publication_holds WHERE issuer_id=? AND language=? AND standard=?", key)
        prior = connection.execute(
            "SELECT r.payload FROM sector_publications p JOIN sector_runs r ON r.version=p.version "
            "WHERE p.issuer_id=? AND p.language=? AND p.standard=?", key).fetchone()
        if prior:
            prior_report = json.loads(prior["payload"])
            report["availability"]["last_successful_period"] = prior_report["period"]
            if report["status"] != "available":
                report["last_successful_report"] = {
                    k: prior_report.get(k) for k in ("version", "period", "financial_as_of", "generated_at", "headline", "paragraphs", "sources")
                }
        stamp = report.get("generated_at") or now()
        report["generated_at"] = stamp
        connection.execute(
            "INSERT INTO sector_runs VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(version) DO NOTHING",
            (report["version"], key[0], report["issuer"]["ticker"], key[1], key[2],
             report["period"], report["status"], stamp, json.dumps(report, ensure_ascii=False)))
        # A public read cannot roll the latest pointer back to an explicitly
        # requested historical report.
        latest = json.loads(prior["payload"]) if prior else {}
        if report["status"] == "available" and str(report.get("financial_as_of") or "") >= str(latest.get("financial_as_of") or ""):
            connection.execute("INSERT INTO sector_publications VALUES (?,?,?,?) ON CONFLICT(issuer_id,language,standard) DO UPDATE SET version=excluded.version", (*key, report["version"]))
    return report


def enqueue(ticker, event, *, actor="source", reason="source_updated"):
    identity = digest([ticker, event, VERSION])
    stamp = now()
    with connect() as connection:
        connection.execute("INSERT INTO sector_jobs VALUES (?,?,?,'queued',0,?,NULL,?) ON CONFLICT(id) DO NOTHING",
                           (identity, ticker, str(event), stamp, stamp))
    return identity


def retry(job_id, actor, reason):
    with connect() as connection:
        old = connection.execute("SELECT * FROM sector_jobs WHERE id=?", (job_id,)).fetchone()
        if not old:
            return False
        connection.execute("UPDATE sector_jobs SET state='queued',attempts=0,next_attempt=?,updated_at=? WHERE id=?", (now(), now(), job_id))
        connection.execute("INSERT INTO sector_audit(actor,action,entity,old_value,new_value,reason,at) VALUES (?,?,?,?,?,?,?)",
                           (actor, "retry", job_id, old["state"], "queued", reason, now()))
    return True




def overview(limit=50):
    with connect() as connection:
        counts = {r["status"]: r["total"] for r in connection.execute("SELECT status,count(*) AS total FROM sector_runs GROUP BY status")}
        runs = [dict(r) for r in connection.execute("SELECT version,issuer_id,ticker,language,standard,period,status,created_at FROM sector_runs ORDER BY created_at DESC LIMIT ?", (limit,))]
        jobs = [dict(r) for r in connection.execute("SELECT * FROM sector_jobs ORDER BY updated_at DESC LIMIT ?", (limit,))]
        audit = [dict(r) for r in connection.execute("SELECT * FROM sector_audit ORDER BY id DESC LIMIT ?", (limit,))]
        overrides = [json.loads(r["payload"]) for r in connection.execute("SELECT payload FROM sector_overrides ORDER BY created_at DESC LIMIT ?", (limit,))]
    from sector_regressions import run
    return {"ok": True, "version": VERSION, "counts": counts, "runs": runs, "jobs": jobs, "audit": audit,
            "overrides": overrides, "regression": run()}


def get_run(version):
    with connect() as connection:
        row = connection.execute("SELECT payload FROM sector_runs WHERE version=?", (version,)).fetchone()
    return json.loads(row["payload"]) if row else None


def active_override(issuer_id, as_of):
    with connect() as connection:
        row = connection.execute("SELECT payload FROM sector_overrides WHERE issuer_id=? AND valid_from<=? AND valid_to>=? ORDER BY created_at DESC LIMIT 1",
                                 (str(issuer_id), as_of, as_of)).fetchone()
    return json.loads(row["payload"]) if row else None


def save_override(issuer, data, actor):
    from sector_regressions import run
    regression = run()
    if regression["status"] != "passed":
        raise ValueError("REGRESSION_GATE_FAILED")
    old = active_override(issuer["id"], data["valid_from"])
    record = {**data, "issuer_id": issuer["id"], "ticker": issuer["ticker"],
              "approved_by": actor, "regression": regression, "created_at": now()}
    record["version"] = digest(record)
    with connect() as connection:
        connection.execute("INSERT INTO sector_overrides VALUES (?,?,?,?,?,?,?)",
                           (record["version"], str(issuer["id"]), issuer["ticker"], data["valid_from"], data["valid_to"],
                            json.dumps(record, ensure_ascii=False), record["created_at"]))
        connection.execute("INSERT INTO sector_audit(actor,action,entity,old_value,new_value,reason,at) VALUES (?,?,?,?,?,?,?)",
                           (actor, "template_override", str(issuer["id"]), json.dumps(old), json.dumps(record, ensure_ascii=False), data["reason_code"], now()))
    enqueue(issuer["ticker"], "rule:" + record["version"])
    return record


def rollback(version, actor, reason):
    report = get_run(version)
    if not report or report["status"] != "available":
        return False
    key = (str(report["issuer"]["id"]), report["language"], report["standard"])
    with connect() as connection:
        old = connection.execute("SELECT p.version,r.payload FROM sector_publications p JOIN sector_runs r ON r.version=p.version WHERE p.issuer_id=? AND p.language=? AND p.standard=?", key).fetchone()
        rejected = json.loads(old["payload"]) if old else report
        identity = digest([rejected.get("source_snapshot_hash"), rejected.get("template_resolution"), rejected.get("calculation_version")])
        connection.execute("INSERT INTO sector_publications VALUES (?,?,?,?) ON CONFLICT(issuer_id,language,standard) DO UPDATE SET version=excluded.version", (*key, version))
        connection.execute("INSERT INTO sector_publication_holds VALUES (?,?,?,?,?) ON CONFLICT(issuer_id,language,standard) DO UPDATE SET version=excluded.version,rejected_identity=excluded.rejected_identity", (*key, version, identity))
        connection.execute("INSERT INTO sector_audit(actor,action,entity,old_value,new_value,reason,at) VALUES (?,?,?,?,?,?,?)",
                           (actor, "publication_rollback", key[0], old["version"] if old else None, version, reason, now()))
    return True
