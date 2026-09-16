"""Indexed read models, immutable revisions and a transactional durable job outbox.

The existing dbx driver keeps local SQLite and production PostgreSQL compatible.
Every key includes the environment; jobs are never submitted to another environment.
"""
from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import dbx
from db import APP_DATA_DIR

COLLECTIONS = frozenset({"issuers", "documents", "coverage", "parsers", "facts", "calculations",
                         "rules", "incidents", "analyses", "publications", "sources", "securities", "jobs", "access"})
FILTERS = {"ticker", "status", "standard", "period", "severity", "source", "category"}
SORTS = FILTERS | {"id", "updated_at"}
REVISION_KEEP_PER_OBJECT = max(1, int(os.getenv("ADMIN_REVISION_KEEP", "10")))
REVISION_KEEP_DAYS = max(1, int(os.getenv("ADMIN_REVISION_KEEP_DAYS", "90")))


class ControlError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def now():
    return datetime.now(timezone.utc).isoformat()


def environment():
    return os.getenv("ADMIN_ENVIRONMENT", os.getenv("RAILWAY_ENVIRONMENT_NAME", "local")).strip().lower()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex


def schema(c):
    c.executescript("""
        CREATE TABLE IF NOT EXISTS control_resources (
          environment TEXT NOT NULL, collection TEXT NOT NULL, id TEXT NOT NULL,
          ticker TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '', standard TEXT NOT NULL DEFAULT '',
          period TEXT NOT NULL DEFAULT '', severity TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL, updated_at TEXT NOT NULL,
          search_text TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(environment,collection,id));
        CREATE INDEX IF NOT EXISTS control_list ON control_resources(environment,collection,updated_at,id);
        CREATE INDEX IF NOT EXISTS control_filter ON control_resources(environment,collection,ticker,status,standard,period);
        CREATE TABLE IF NOT EXISTS control_revisions (
          environment TEXT NOT NULL, collection TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
          created_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(environment,collection,id,version));
        CREATE TABLE IF NOT EXISTS control_audit (
          id TEXT PRIMARY KEY, environment TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL,
          action TEXT NOT NULL, entity_id TEXT NOT NULL, reason TEXT NOT NULL, request_id TEXT NOT NULL,
          result TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS control_audit_filter ON control_audit(environment,created_at,id);
        CREATE TABLE IF NOT EXISTS control_commands (
          environment TEXT NOT NULL, actor TEXT NOT NULL, command_key TEXT NOT NULL,
          fingerprint TEXT NOT NULL, response TEXT, PRIMARY KEY(environment,actor,command_key));
        CREATE TABLE IF NOT EXISTS control_lock (id INTEGER PRIMARY KEY, counter INTEGER NOT NULL);
    """)
    # No application API can delete history. Database triggers also protect it
    # from accidental UPDATE/DELETE through the application connection.
    if dbx.backend() == dbx.SQLITE:
        # Revision retention is a bounded, internal maintenance operation.  It
        # must not turn the public/admin API into a delete-capable interface,
        # nor does it apply to the append-only audit log.
        if "revision_prune" not in dbx.columns(c, "control_lock"):
            c.execute("ALTER TABLE control_lock ADD COLUMN revision_prune INTEGER NOT NULL DEFAULT 0")
        c.execute("CREATE TRIGGER IF NOT EXISTS control_audit_update BEFORE UPDATE ON control_audit "
                  "BEGIN SELECT RAISE(ABORT, 'immutable history'); END")
        c.execute("CREATE TRIGGER IF NOT EXISTS control_audit_delete BEFORE DELETE ON control_audit "
                  "BEGIN SELECT RAISE(ABORT, 'immutable history'); END")
        c.execute("CREATE TRIGGER IF NOT EXISTS control_revisions_update BEFORE UPDATE ON control_revisions "
                  "BEGIN SELECT RAISE(ABORT, 'immutable history'); END")
        # Replace the v1 trigger once, so production SQLite gets the same
        # revision bounds as PostgreSQL.  The guard is set only around the
        # explicit maintenance query below.
        c.execute("DROP TRIGGER IF EXISTS control_revisions_delete")
        c.execute(
            "CREATE TRIGGER control_revisions_delete BEFORE DELETE ON control_revisions "
            "WHEN COALESCE((SELECT revision_prune FROM control_lock WHERE id=1), 0) <> 1 "
            "BEGIN SELECT RAISE(ABORT, 'immutable history'); END"
        )
    else:
        c.execute("CREATE OR REPLACE FUNCTION control_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ "
                  "BEGIN IF TG_OP = 'DELETE' AND current_setting('app.revision_prune', true) = 'on' "
                  "THEN RETURN OLD; END IF; RAISE EXCEPTION 'immutable history'; END; $$")
        for table in ("control_audit", "control_revisions"):
            trigger = f"{table}_immutable"
            c.execute(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = '{trigger}' AND NOT tgisinternal) THEN "
                f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION control_immutable(); END IF; END $$"
            )
    c.commit()


@contextmanager
def connection(write=False):
    path = Path(os.getenv("ADMIN_CONTROL_DB") or APP_DATA_DIR / "admin_control.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    c = dbx.connect(str(path))
    try:
        # A rolling deployment can start several workers at once. PostgreSQL
        # may then deadlock one worker while identical idempotent DDL/upserts
        # initialise the control schema on separate pooled connections. Retry
        # only that transient transaction state; application/data errors must
        # still fail immediately.
        for attempt in range(3):
            try:
                dbx.ensure_schema(c, "admin-control-v2", schema)
                break
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "40P01" or attempt == 2:
                    raise
                c.rollback()
                time.sleep(0.05 * (attempt + 1))
        if write:
            # Serialize short commands across processes, including the first insert.
            # No external I/O is performed while this transaction is held.
            c.execute("INSERT INTO control_lock(id,counter) VALUES (1,0) ON CONFLICT(id) DO NOTHING")
            c.execute("UPDATE control_lock SET counter=counter+1 WHERE id=1")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def get(c, collection, entity_id, required=True):
    row = c.execute("SELECT payload FROM control_resources WHERE environment=? AND collection=? AND id=?",
                    (environment(), collection, str(entity_id))).fetchone()
    if not row and required:
        raise ControlError("NOT_FOUND", "The requested object does not exist in this environment.", 404)
    return json.loads(row["payload"]) if row else None


def put(c, collection, value, *, expected=None):
    if collection not in COLLECTIONS:
        raise ControlError("INVALID_COLLECTION", "Unknown registry.", 404)
    item = dict(value)
    entity_id = str(item["id"])
    old = get(c, collection, entity_id, False)
    if expected is not None and (old or {}).get("version", 0) != expected:
        raise ControlError("VERSION_CONFLICT", "This object changed. Refresh and compare before trying again.")
    content = lambda obj: {k: v for k, v in obj.items() if k not in {"version", "updated_at"}}
    if old and content(old) == content(item):
        return old
    item.update(version=(old or {}).get("version", 0) + 1, updated_at=now())
    columns = [str(item.get(k) or "") for k in ("ticker", "status", "standard", "period", "severity", "source", "category")]
    payload = encode(item)
    # Values, never SQL identifiers, come from the caller.
    c.execute("INSERT INTO control_resources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
              "ON CONFLICT(environment,collection,id) DO UPDATE SET ticker=excluded.ticker,status=excluded.status,"
              "standard=excluded.standard,period=excluded.period,severity=excluded.severity,source=excluded.source,"
              "category=excluded.category,version=excluded.version,updated_at=excluded.updated_at,"
              "search_text=excluded.search_text,payload=excluded.payload",
              (environment(), collection, entity_id, *columns, item["version"], item["updated_at"], payload.lower(), payload))
    c.execute("INSERT INTO control_revisions VALUES (?,?,?,?,?,?)",
              (environment(), collection, entity_id, item["version"], item["updated_at"], payload))
    _prune_revisions(c, environment(), collection, entity_id, item["version"])
    return item


def _prune_revisions(c, env, collection, entity_id, current_version):
    """Bound revision storage while preserving the current snapshot.

    The control API still cannot delete history: the immutable trigger permits
    this narrowly scoped maintenance delete only inside the current transaction.
    """
    if dbx.backend() == dbx.SQLITE:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=REVISION_KEEP_DAYS)).isoformat()
        c.execute("UPDATE control_lock SET revision_prune=1 WHERE id=1")
        try:
            c.execute(
                """
                DELETE FROM control_revisions
                WHERE environment=? AND collection=? AND id=? AND version<>?
                  AND (
                    version NOT IN (
                      SELECT version FROM control_revisions
                      WHERE environment=? AND collection=? AND id=?
                      ORDER BY version DESC LIMIT ?
                    )
                    OR created_at < ?
                  )
                """,
                (env, collection, entity_id, current_version,
                 env, collection, entity_id, REVISION_KEEP_PER_OBJECT, cutoff),
            )
        finally:
            c.execute("UPDATE control_lock SET revision_prune=0 WHERE id=1")
        return
    c.execute("SELECT set_config('app.revision_prune', 'on', true)")
    try:
        c.execute(
            """
            DELETE FROM control_revisions
            WHERE environment=? AND collection=? AND id=? AND version<>?
              AND (
                version NOT IN (
                  SELECT version FROM control_revisions
                  WHERE environment=? AND collection=? AND id=?
                  ORDER BY version DESC LIMIT ?
                )
                OR created_at < to_char(
                  now() AT TIME ZONE 'UTC' - (? * interval '1 day'),
                  'YYYY-MM-DD"T"HH24:MI:SS'
                )
              )
            """,
            (env, collection, entity_id, current_version,
             env, collection, entity_id, REVISION_KEEP_PER_OBJECT,
             REVISION_KEEP_DAYS),
        )
    finally:
        c.execute("SELECT set_config('app.revision_prune', 'off', true)")


def audit(c, actor, action, entity, reason, request_id, old=None, new=None, result="success"):
    event = {"id": uid("audit"), "environment": environment(), "actor": actor["email"], "role": actor["role"],
             "action": action, "entity_id": str(entity), "reason": reason, "request_id": request_id,
             "old": old, "new": new, "result": result, "created_at": now()}
    c.execute("INSERT INTO control_audit VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              tuple(event[k] for k in ("id", "environment", "actor", "role", "action", "entity_id", "reason", "request_id", "result", "created_at")) + (encode(event),))
    return event


def query(c, collection, params=None, *, limit=50):
    params = dict(params or {})
    if collection != "audit" and collection not in COLLECTIONS:
        raise ControlError("NOT_FOUND", "Unknown registry.", 404)
    table = "control_audit" if collection == "audit" else "control_resources"
    clauses, args = ["environment=?"], [environment()]
    if collection != "audit":
        clauses.append("collection=?")
        args.append(collection)
    valid = {"actor", "action", "entity_id", "result", "role"} if collection == "audit" else FILTERS
    if collection in {"documents", "coverage"} and "DUPLICATE" not in str(params.get("status") or "").split(","):
        clauses.append("status<>'DUPLICATE'")
    for field in valid:
        values = [v for v in str(params.get(field) or "").split(",") if v]
        if values:
            clauses.append(field + " IN (" + ",".join("?" for _ in values) + ")")
            args.extend(values)
    if params.get("q"):
        field = "payload" if collection == "audit" else "search_text"
        q = str(params["q"]).lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append(f"LOWER({field}) LIKE ? ESCAPE '\\'")
        args.append("%" + q + "%")
    sorts = {"created_at", "id", "actor", "action"} if collection == "audit" else SORTS
    sort = params.get("sort", "created_at" if collection == "audit" else "updated_at")
    if sort not in sorts:
        raise ControlError("INVALID_SORT", "Unsupported sort column.", 422)
    direction = "ASC" if params.get("direction") == "asc" else "DESC"
    fingerprint = digest({k: v for k, v in params.items() if k not in {"cursor", "limit", "format"}})
    total = c.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE " + " AND ".join(clauses), tuple(args)).fetchone()["n"]
    if params.get("cursor"):
        try:
            cursor = json.loads(base64.urlsafe_b64decode(params["cursor"]).decode())
            if cursor["filter"] != fingerprint:
                raise ValueError()
            comparator = ">" if direction == "ASC" else "<"
            clauses.append(f"({sort}{comparator}? OR ({sort}=? AND id{comparator}?))")
            args.extend([cursor["value"], cursor["value"], cursor["id"]])
        except (ValueError, KeyError, TypeError, binascii.Error):
            raise ControlError("INVALID_CURSOR", "Reset pagination after changing filters.", 422) from None
    limit = max(1, min(int(limit), 100))
    rows = c.execute(f"SELECT * FROM {table} WHERE " + " AND ".join(clauses) +
                     f" ORDER BY {sort} {direction},id {direction} LIMIT ?", (*args, limit + 1)).fetchall()
    items = [json.loads(r["payload"]) for r in rows[:limit]]
    cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        cursor = base64.urlsafe_b64encode(encode({"value": last[sort], "id": last["id"], "filter": fingerprint}).encode()).decode()
    return {"items": items, "total": total, "next_cursor": cursor, "limit": limit}


def all_items(c, collection, params=None):
    params = dict(params or {})
    while True:
        page = query(c, collection, params, limit=100)
        yield from page["items"]
        if not page["next_cursor"]:
            break
        params["cursor"] = page["next_cursor"]


def command(actor, key, payload, request_id, callback):
    if not key or not 8 <= len(key) <= 200:
        raise ControlError("IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key of 8–200 characters.", 422)
    fingerprint = digest(payload)
    with connection(write=True) as c:
        row = c.execute("SELECT * FROM control_commands WHERE environment=? AND actor=? AND command_key=?",
                        (environment(), actor["email"], key)).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise ControlError("IDEMPOTENCY_CONFLICT", "This key was already used for a different command.")
            return json.loads(row["response"])
        result = {**callback(c), "request_id": request_id}
        c.execute("INSERT INTO control_commands VALUES (?,?,?,?,?)",
                  (environment(), actor["email"], key, fingerprint, encode(result)))
        return result
