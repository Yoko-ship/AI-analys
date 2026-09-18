"""Discovery and content-addressed, durable original files."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from . import store

FETCH_VERSION = "bounded-openinfo-v1"


def artifact_root():
    from db import APP_DATA_DIR
    root = Path(os.environ.get("FINANCIAL_ARTIFACT_DIR") or APP_DATA_DIR / "financial_artifacts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def archive(payload: bytes):
    sha = hashlib.sha256(payload).hexdigest()
    relative = sha[:2] + "/" + sha + ".pdf"
    path = artifact_root() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd, scratch = tempfile.mkstemp(dir=path.parent, prefix=".incoming-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(scratch, path)  # create-only, never overwrite evidence
            except FileExistsError:
                pass
        finally:
            os.unlink(scratch)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError("Stored original failed its integrity check")
    return sha, relative


def read_artifact(sha):
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Invalid artifact identifier")
    path = artifact_root() / sha[:2] / (sha + ".pdf")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != sha:
        raise ValueError("Archived file is corrupt")
    return content


def register(c, *, org_id, ticker, url, category, metadata, processor, refresh_days=7):
    source_id = store.digest([str(org_id), url])
    old = c.execute("SELECT * FROM ingest_sources WHERE id=?", (source_id,)).fetchone()
    c.execute("INSERT INTO ingest_sources (id,org_id,ticker,url,category,metadata_json,first_seen,last_seen) "
              "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET metadata_json=excluded.metadata_json,"
              "last_seen=excluded.last_seen,category=excluded.category",
              (source_id, str(org_id), ticker, url, category, store.encoded(metadata), store.now(), store.now()))
    # A refreshed source gets a new job, while an unfinished attempt retains
    # its retry schedule. Failed jobs require an explicit operator retry.
    active = c.execute("SELECT 1 FROM ingest_jobs WHERE source_id=? AND stage='FETCH' "
                       "AND state IN ('QUEUED','RUNNING','RETRY','FAILED')", (source_id,)).fetchone()
    if not active and (not old or not old["checked_at"] or old["checked_at"] < time.time() - refresh_days * 86400):
        store.enqueue(c, source_id, "FETCH", FETCH_VERSION, generation=str(old["checked_at"] if old else "initial"))
    if old and old["latest_version"]:
        store.enqueue(c, source_id, "EXTRACT", processor, version_id=old["latest_version"])
    return source_id


def discover(*, ticker=None, processor):
    # NSBU continues through its established workbook collector. Only PDF
    # candidates enter this rollout; it does not take ownership of NSBU writes.
    import reports_catalog as rc
    c = rc.get_catalog_conn()
    try:
        rows = c.execute("SELECT r.*,c.org_id FROM catalog_reports r JOIN catalog_companies c ON c.ticker=r.ticker "
                         "WHERE r.report_form IN ('MSFO','Audition') AND r.pdf_url IS NOT NULL "
                         "AND c.org_id IS NOT NULL" + (" AND c.org_id=(SELECT org_id FROM catalog_companies WHERE ticker=?)" if ticker else
                         " AND EXISTS (SELECT 1 FROM catalog_companies b JOIN catalog_reports n ON n.ticker=b.ticker "
                         "WHERE b.org_id=c.org_id AND n.report_form='NSBU' AND "
                         "(n.excel_url LIKE '%org_type=bank%' OR n.excel_url_form1 LIKE '%org_type=bank%'))"),
                         (ticker.upper(),) if ticker else ()).fetchall()
    finally:
        c.close()
    ids = set()
    with store.transaction() as c:
        for row in rows:
            ids.add(register(c, org_id=row["org_id"], ticker=row["ticker"], url=row["pdf_url"],
                             category=row["report_form"], metadata=dict(row), processor=processor))
    return {"sources": len(ids)}


def fetch_job(job, processor, fetch=None):
    from ifrs_financials import download_pdf
    fetch = fetch or download_pdf
    c = store.connect()
    try:
        source = dict(c.execute("SELECT * FROM ingest_sources WHERE id=?", (job["source_id"],)).fetchone())
    finally:
        c.close()
    payload = fetch(source["url"])
    if not payload.startswith(b"%PDF-"):
        raise ValueError("Source did not return a PDF")
    sha, path = archive(payload)
    version_id = store.digest([source["id"], sha])
    with store.transaction() as c:
        store.assert_lease(c, job)
        c.execute("INSERT INTO ingest_artifacts VALUES (?,?,?,?,?) ON CONFLICT(sha) DO NOTHING",
                  (sha, path, len(payload), "application/pdf", store.now()))
        c.execute("INSERT INTO ingest_versions VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                  (version_id, source["id"], sha, source["metadata_json"], store.now()))
        c.execute("UPDATE ingest_sources SET latest_version=?,checked_at=? WHERE id=?", (version_id, time.time(), source["id"]))
        if source["latest_version"] and source["latest_version"] != version_id:
            store.event(c, source["id"], "source.replaced", old_version=source["latest_version"], new_version=version_id)
        store.enqueue(c, source["id"], "EXTRACT", processor, version_id=version_id)
        store.finish(c, job, "SUCCEEDED")
    return version_id


def issuer_artifact(ticker, sha):
    """Only serve bytes linked to a published snapshot for this issuer."""
    import reports_catalog as rc
    import dbx
    c = rc.get_catalog_conn()
    try:
        if "ingest_snapshots" not in dbx.tables(c):
            return None
        row = c.execute("SELECT 1 FROM ingest_snapshots p JOIN ingest_candidates x ON x.id=p.candidate_id "
                        "JOIN ingest_versions v ON v.id=x.version_id WHERE v.sha=? "
                        "AND p.org_id=(SELECT org_id FROM catalog_companies WHERE ticker=?) LIMIT 1",
                        (sha, ticker.upper())).fetchone()
    finally:
        c.close()
    return read_artifact(sha) if row else None
