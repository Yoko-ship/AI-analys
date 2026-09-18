"""Discovery and content-addressed, durable original files."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlparse, urljoin

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
        # Only explicitly reviewed issuer-site documents extend OpenInfo's
        # catalog. This is not a crawler or an unrestricted URL import path.
        from .extract import review_entries
        for entry in review_entries():
            if entry.get("source_kind") != "issuer_website" or (ticker and entry["ticker"] != ticker.upper()):
                continue
            company = c.execute("SELECT org_id FROM catalog_companies WHERE ticker=?", (entry["ticker"],)).fetchone()
            if not company or str(company["org_id"]) != str(entry["org_id"]):
                raise ValueError("Reviewed issuer-site source does not match the catalog issuer")
            ids.add(register(c, org_id=entry["org_id"], ticker=entry["ticker"], url=entry["pdf_url"],
                             category="IssuerIFRS", processor=processor, metadata={
                                 "report_form": "MSFO", "source_page_url": entry["source_page_url"],
                                 "title": entry["issuer_name"] + " reviewed IFRS statements",
                                 "year": entry["document_year"], "quarter": 0,
                             }))
        # Registered issuer originals participate in refresh/reprocessing just
        # like catalog documents, without entries in a checked-in value ledger.
        for source in c.execute("SELECT * FROM ingest_sources WHERE category='IssuerIFRS'").fetchall():
            metadata = json.loads(source["metadata_json"])
            if not metadata.get("registered_by") or (ticker and source["ticker"] != ticker.upper()):
                continue
            ids.add(register(c, org_id=source["org_id"], ticker=source["ticker"], url=source["url"],
                             category=source["category"], metadata=metadata, processor=processor))
    from . import disclosures
    attachments = disclosures.discover(ticker=ticker, processor=processor)
    return {"sources": len(ids), "annual_attachments": attachments}


def register_issuer_source(*, ticker, url, source_page, actor, reason, processor):
    """Register an issuer original without adding Python rules or value JSON.

    Operator attribution records who verified the issuer's source page. The
    file still follows FETCH → EXTRACT → review and cannot publish itself.
    """
    import ipaddress
    import socket
    import reports_catalog as rc
    if not actor.strip() or not reason.strip():
        raise ValueError("Source registration requires actor and reason")
    company = rc.get_company_index(ticker.upper()) or {}
    if not company.get("org_id"):
        raise ValueError("Known catalog issuer required")
    parsed, origin = urlparse(url), urlparse(source_page)
    for target in (parsed, origin):
        if (target.scheme != "https" or not target.hostname or target.port not in {None,443}
                or target.username or target.password or target.fragment):
            raise ValueError("Issuer sources require public HTTPS URLs without credentials")
    for target in (parsed, origin):
        addresses = socket.getaddrinfo(target.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(record[4][0]).is_global for record in addresses):
            raise ValueError("Issuer source must resolve to public addresses")
    linked_origin = None
    page_sha = None
    if parsed.hostname != origin.hostname:
        # Issuers commonly host PDFs on a separate asset/API domain. Require
        # an actual link on the attributed public source page, never a suffix
        # match or a company-specific hostname exception.
        import requests
        from bs4 import BeautifulSoup
        with requests.get(source_page, stream=True, timeout=(15,30), allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError("Issuer source page must return HTTP 200 without redirects")
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > 4 * 1024 * 1024:
                    raise ValueError("Issuer source page exceeds size limit")
        links = {urljoin(source_page, a['href']) for a in BeautifulSoup(bytes(content), 'html.parser').select('a[href]')}
        if url not in links:
            raise ValueError("PDF must share an origin or be linked by the verified issuer source page")
        linked_origin = f'https://{parsed.netloc}'
        page_sha = hashlib.sha256(content).hexdigest()
    with store.transaction() as c:
        source = register(c, org_id=company['org_id'], ticker=ticker.upper(), url=url,
                          category="IssuerIFRS", processor=processor, metadata={
                              "report_form":"MSFO", "source_page_url":source_page,
                              "linked_document_origin":linked_origin, "source_page_sha256":page_sha,
                              "title":company.get("company_name") or ticker.upper(),
                              "registered_by":actor, "registration_reason":reason})
        store.event(c, source, "source.registered", actor=actor, reason=reason, source_page=source_page)
    return {"source":source}


def fetch_job(job, processor, fetch=None):
    from ifrs_financials import download_pdf
    c = store.connect()
    try:
        source = dict(c.execute("SELECT * FROM ingest_sources WHERE id=?", (job["source_id"],)).fetchone())
    finally:
        c.close()
    metadata = json.loads(source["metadata_json"])
    payload = (fetch(source["url"]) if fetch else download_pdf(source["url"],
               issuer_origin=(metadata.get("linked_document_origin") or metadata.get("source_page_url"))
               if source["category"] == "IssuerIFRS" else None))
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
