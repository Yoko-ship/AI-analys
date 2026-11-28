"""Transactional workspace records; append-only history, isolated by environment.

The database lock protects short read/modify/write operations across workers.
External I/O must happen outside this transaction, after a durable claim.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

import dbx
from db import APP_DATA_DIR
from .errors import MarketingError


def now():
    return datetime.now(timezone.utc).isoformat()


def environment():
    return os.getenv("MARKETING_ENVIRONMENT", os.getenv("ADMIN_ENVIRONMENT", "local"))


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def schema(c):
    c.executescript("""
        CREATE TABLE IF NOT EXISTS marketing_records (
          environment TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
          version INTEGER NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL,
          payload TEXT NOT NULL, PRIMARY KEY(environment,kind,id));
        CREATE INDEX IF NOT EXISTS marketing_status ON marketing_records(environment,kind,status,updated_at);
        CREATE TABLE IF NOT EXISTS marketing_revisions (
          environment TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
          version INTEGER NOT NULL, created_at TEXT NOT NULL, actor TEXT NOT NULL,
          action TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(environment,kind,id,version));
        CREATE TABLE IF NOT EXISTS marketing_lock (id INTEGER PRIMARY KEY, counter INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS marketing_credentials (
          environment TEXT NOT NULL, account_id TEXT NOT NULL, provider TEXT NOT NULL,
          ciphertext TEXT NOT NULL, PRIMARY KEY(environment,account_id,provider));
        CREATE TABLE IF NOT EXISTS marketing_oauth_states (
          environment TEXT NOT NULL, state_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
          payload TEXT NOT NULL, PRIMARY KEY(environment,state_hash));
    """)
    if dbx.backend() == dbx.SQLITE:
        for action in ("UPDATE", "DELETE"):
            c.execute(f"CREATE TRIGGER IF NOT EXISTS marketing_history_{action.lower()} "
                      f"BEFORE {action} ON marketing_revisions BEGIN SELECT RAISE(ABORT, 'immutable history'); END")
    else:
        c.execute("CREATE OR REPLACE FUNCTION marketing_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ "
                  "BEGIN RAISE EXCEPTION 'immutable history'; END; $$")
        c.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='marketing_history_immutable' "
                  "AND NOT tgisinternal) THEN CREATE TRIGGER marketing_history_immutable BEFORE UPDATE OR DELETE "
                  "ON marketing_revisions FOR EACH ROW EXECUTE FUNCTION marketing_immutable(); END IF; END $$")
    c.commit()


@contextmanager
def connection(write=False):
    path = Path(os.getenv("MARKETING_DB") or APP_DATA_DIR / "marketing.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    c = dbx.connect(str(path))
    try:
        dbx.ensure_schema(c, "marketing-v2", schema)
        if write:
            c.execute("INSERT INTO marketing_lock(id,counter) VALUES (1,0) ON CONFLICT(id) DO NOTHING")
            c.execute("UPDATE marketing_lock SET counter=counter+1 WHERE id=1")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def get(c, kind, record_id, required=True):
    row = c.execute("SELECT payload FROM marketing_records WHERE environment=? AND kind=? AND id=?",
                    (environment(), kind, record_id)).fetchone()
    if row:
        return json.loads(row["payload"])
    if required:
        raise MarketingError("NOT_FOUND", f"Missing {kind}: {record_id}", 404)
    return None


def list_items(c, kind, status=None):
    query = "SELECT payload FROM marketing_records WHERE environment=? AND kind=?"
    args = [environment(), kind]
    if status is not None:
        query += " AND status=?"
        args.append(status)
    return [json.loads(r["payload"]) for r in c.execute(query + " ORDER BY updated_at DESC,id", args).fetchall()]


def history(c, kind, record_id):
    return [{"actor": json.loads(r["actor"]), "action": r["action"], "record": json.loads(r["payload"])}
            for r in c.execute("SELECT actor,action,payload FROM marketing_revisions WHERE environment=? "
                               "AND kind=? AND id=? ORDER BY version", (environment(), kind, record_id)).fetchall()]


def revision(c, kind, record_id, version):
    row = c.execute("SELECT payload FROM marketing_revisions WHERE environment=? AND kind=? AND id=? AND version=?",
                    (environment(), kind, record_id, version)).fetchone()
    return json.loads(row["payload"]) if row else None


def put(c, kind, record, *, actor, action, expected_version):
    previous = get(c, kind, record["id"], required=False)
    version = previous["version"] if previous else 0
    if version != expected_version:
        raise MarketingError("VERSION_CONFLICT", "This record changed. Reload before saving.")
    value = {**record, "version": version + 1, "updated_at": now()}
    payload = encode(value)
    c.execute("INSERT INTO marketing_records(environment,kind,id,version,status,updated_at,payload) VALUES (?,?,?,?,?,?,?) "
              "ON CONFLICT(environment,kind,id) DO UPDATE SET version=excluded.version,status=excluded.status,"
              "updated_at=excluded.updated_at,payload=excluded.payload",
              (environment(), kind, value["id"], value["version"], value.get("status", ""), value["updated_at"], payload))
    c.execute("INSERT INTO marketing_revisions(environment,kind,id,version,created_at,actor,action,payload) VALUES (?,?,?,?,?,?,?,?)",
              (environment(), kind, value["id"], value["version"], value["updated_at"], encode(actor), action, payload))
    return value
