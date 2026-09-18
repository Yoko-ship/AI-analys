"""Discover PDF attachments inside OpenInfo annual filings, independently of NSBU values."""
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from . import store

API = "https://new-api.openinfo.uz/api/v2"
WEB = "https://openinfo.uz"
REFRESH_SECONDS = 7 * 86400


def remember(c, *, ticker, org_id, org_type, report_id):
    if not re.fullmatch(r"[a-z_]+", str(org_type)) or not str(report_id).isdigit():
        return
    path = f"/reports/{org_type}/annual/{report_id}/"
    key = store.digest([str(org_id), path])
    c.execute("INSERT INTO ingest_disclosures (id,org_id,ticker,api_path) VALUES (?,?,?,?) "
              "ON CONFLICT(id) DO NOTHING", (key, str(org_id), ticker, path))


def remember_listing(*, ticker, org_id, records):
    # The parent filing may be excluded from NSBU ingestion for bad numbers.
    # Its independently audited attachment still deserves discovery/review.
    with store.transaction() as c:
        for rec in records:
            props = rec.get("properties") or {}
            if (str(rec.get("organization")) == str(org_id) and rec.get("report_type") == "NSBU"
                    and props.get("report_type") == "annual"):
                remember(c, ticker=ticker, org_id=org_id, org_type=props.get("org_type"),
                         report_id=rec.get("object_id"))


def _fetch(path):
    from openinfo_http import shared_session
    with shared_session().get(API + path, stream=True, timeout=(10, 20), allow_redirects=False) as r:
        if r.status_code != 200:
            raise ValueError(f"Annual disclosure returned HTTP {r.status_code}")
        content = bytearray()
        for chunk in r.iter_content(65536):
            content.extend(chunk)
            if len(content) > 8 * 1024 * 1024:
                raise ValueError("Annual disclosure exceeds size limit")
    return json.loads(content)


def _attachments(detail, row):
    org = detail.get("organization") or {}
    expected_id = row["api_path"].strip("/").split("/")[-1]
    if not isinstance(org, dict) or str(org.get("id")) != row["org_id"] or str(detail.get("id")) != expected_id:
        raise ValueError("Annual disclosure issuer or record does not match request")
    files = [(detail.get("int_report"), "MSFO", "int_report")]
    for audit in detail.get("audition_result_report") or []:
        if audit.get("main_report") is not None and str(audit["main_report"]) != expected_id:
            raise ValueError("Audit attachment belongs to a different annual disclosure")
        files.append((audit.get("conclusion_file"), "Audition", "audition_result_report"))
    found = {}
    for value, category, field in files:
        if not value:
            continue
        url = urljoin(WEB + "/media/", str(value))
        parsed = urlparse(url)
        path = unquote(parsed.path)
        if (parsed.scheme != "https" or parsed.netloc != "openinfo.uz" or parsed.query or parsed.fragment
                or not path.startswith("/media/") or not path.lower().endswith(".pdf")
                or ".." in path.split("/") or "\\" in path):
            raise ValueError("Annual attachment is not an OpenInfo media PDF")
        found.setdefault(url, {"url": url, "category": category, "metadata": {
            "source_page_url": WEB + "/ru" + row["api_path"].rstrip("/"),
            "source_api_url": API + row["api_path"], "attachment_field": field,
            "disclosure_id": expected_id, "parent_id": detail.get("parent_id"),
            "disclosure_sha256": hashlib.sha256(store.encoded(detail).encode()).hexdigest(),
            "report_form": category,
        }})
    return list(found.values())


def discover(*, ticker=None, processor, max_requests=8, fetch=None):
    from .documents import register
    fetch = fetch or _fetch
    # Bootstrap historical catalog rows; normal catalog sync also remembers
    # every annual parent, including parents excluded from NSBU value ingestion.
    with store.transaction() as c:
        annuals = c.execute("SELECT r.*,c.org_id FROM catalog_reports r JOIN catalog_companies c ON c.ticker=r.ticker "
                            "WHERE r.report_form='NSBU' AND r.period_type='annual' AND c.org_id IS NOT NULL").fetchall()
        for row in annuals:
            parsed = urlparse(row["excel_url"] or row["excel_url_form1"] or "")
            query = parse_qs(parsed.query)
            if parsed.scheme == "https" and parsed.netloc == "new-api.openinfo.uz" and parsed.path == "/api/v2/reports/export-excel/":
                remember(c, ticker=row["ticker"], org_id=row["org_id"],
                         org_type=query.get("org_type", [None])[0], report_id=query.get("report_id", [None])[0])
        rows = [dict(r) for r in c.execute(
            "SELECT d.* FROM ingest_disclosures d WHERE EXISTS (SELECT 1 FROM catalog_companies c "
            "WHERE c.org_id=d.org_id AND c.ticker=d.ticker)" +
            (" AND d.org_id=(SELECT org_id FROM catalog_companies WHERE ticker=?)" if ticker else
             " AND d.api_path LIKE '/reports/bank/annual/%'") +
            " ORDER BY COALESCE(d.checked_at,0),d.id", (ticker.upper(),) if ticker else ()).fetchall()]
    requested, errors, ids = 0, [], set()
    started = time.monotonic()
    for row in rows:
        attachments = json.loads(row["attachments_json"])
        due = row["retry_at"] <= time.time()
        if due and requested < max_requests and time.monotonic() - started < 60:
            requested += 1
            try:
                attachments = _attachments(fetch(row["api_path"]), row)
                with store.transaction() as c:
                    c.execute("UPDATE ingest_disclosures SET checked_at=?,retry_at=?,attachments_json=?,error=NULL WHERE id=?",
                              (time.time(), time.time() + REFRESH_SECONDS, store.encoded(attachments), row["id"]))
                    store.event(c, row["id"], "disclosure.discovered", attachments=len(attachments))
            except Exception as exc:
                error = str(exc)[:1000]
                errors.append({"disclosure": row["id"], "reason": error})
                with store.transaction() as c:
                    c.execute("UPDATE ingest_disclosures SET checked_at=?,retry_at=?,error=? WHERE id=?",
                              (time.time(), time.time() + 3600, error, row["id"]))
                    store.event(c, row["id"], "disclosure.failed", reason=error)
        # A transient refresh failure retains the last verified attachment set.
        with store.transaction() as c:
            for attachment in attachments:
                ids.add(register(c, org_id=row["org_id"], ticker=row["ticker"], processor=processor,
                                 **attachment))
    return {"sources": len(ids), "requests": requested, "errors": errors,
            "pending": sum(r["retry_at"] <= time.time() for r in rows) - requested}
