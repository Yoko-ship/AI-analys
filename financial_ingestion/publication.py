"""Explicit approval, atomic snapshot publication, rollback and public evidence."""
from decimal import Decimal
import json

from . import documents, source_policy, store, validation


def period_key(meta):
    """Only calendar annuals and explicitly dated cumulative interim periods."""
    start, end = meta.get("period_start") or "", meta.get("period_end") or ""
    if start[5:] != "01-01" or start[:4] != end[:4]:
        return None
    if end[5:] == "12-31":
        return end[:4]
    quarter = {"03-31": 1, "06-30": 2, "09-30": 3}.get(end[5:])
    return f"{end[:4]}Q{quarter}" if quarter else None


def propose(candidate_id, payload, *, actor, reason):
    """A reviewed correction creates a new candidate; originals stay immutable."""
    if not actor.strip() or not reason.strip():
        raise ValueError("Reviewer identity and reason are required")
    with store.transaction() as c:
        old = c.execute("SELECT * FROM ingest_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not old:
            raise ValueError("Unknown candidate")
        original = json.loads(old["payload_json"])
        payload = {**payload, "page_count": original["page_count"]}
        checks = validation.validate(payload, page_count=payload["page_count"])
        if not checks["valid"]:
            raise ValueError("Invalid reviewed proposal: " + ", ".join(checks["errors"]))
        candidate = store.digest([old["version_id"], "reviewed-proposal-v1", payload])
        c.execute("INSERT INTO ingest_candidates VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                  (candidate, old["version_id"], "reviewed-proposal-v1", store.encoded(payload), store.encoded(checks), store.now()))
        store.event(c, candidate, "candidate.corrected", actor=actor, original=candidate_id, reason=reason)
        return candidate


def approve(candidate_id, *, actor, reason):
    if not actor.strip() or not reason.strip():
        raise ValueError("Reviewer identity and reason are required")
    with store.transaction() as c:
        row = c.execute("SELECT * FROM ingest_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise ValueError("Unknown candidate")
        payload = json.loads(row["payload_json"])
        checks = validation.validate(payload, page_count=payload["page_count"])
        if not checks["valid"]:
            raise ValueError("Validation failed: " + ", ".join(checks["errors"]))
        review_id = store.digest([candidate_id, actor, reason])
        c.execute("INSERT INTO ingest_reviews VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                  (review_id, candidate_id, actor, "APPROVED", reason, store.now()))
        store.event(c, candidate_id, "review.approved", actor=actor, reason=reason)
        return review_id


def publish(ticker, *, actor, replace=False, candidate_ids=None):
    """Publish an issuer's reviewed periods in ONE transaction, or none of them.

    Revisions replacing a published candidate need explicit --replace. A worker
    cannot automatically supersede facts just because a PDF or review changed.
    """
    import reports_catalog as rc
    ticker = ticker.strip().upper()
    company = rc.get_company_index(ticker) or {}
    org = str(company.get("org_id") or "")
    if not org or not actor.strip():
        raise ValueError("Known issuer and publication actor are required")
    c = store.connect()
    try:
        rows = c.execute("SELECT x.*,r.id AS review_id,v.sha,v.source_id,v.received_at,s.org_id,s.url,s.category,"
                         "s.latest_version,v.metadata_json FROM ingest_candidates x "
                         "JOIN ingest_reviews r ON r.candidate_id=x.id AND r.decision='APPROVED' "
                         "JOIN ingest_versions v ON v.id=x.version_id JOIN ingest_sources s ON s.id=v.source_id "
                         "WHERE s.org_id=? ORDER BY x.created_at,x.id", (org,)).fetchall()
    finally:
        c.close()
    # Check bytes before acquiring the write lock. The immutable archive is
    # also checked on every public artifact read.
    ready = {}
    for row in rows:
        row = dict(row)
        if candidate_ids is not None and row["id"] not in candidate_ids:
            continue
        if row["version_id"] != row["latest_version"]:
            continue
        documents.read_artifact(row["sha"])
        payload = json.loads(row["payload_json"])
        checks = validation.validate(payload, page_count=payload["page_count"])
        if not checks["valid"]:
            raise ValueError("Approved candidate no longer validates")
        meta = payload["classification"]
        if meta["standard"] != "MSFO" or not period_key(meta):
            continue
        key = (org, meta["standard"], meta["scope"], meta["period_start"], meta["period_end"])
        if key in ready and ready[key][0]["id"] != row["id"]:
            raise ValueError("Conflicting approved candidates: choose explicit candidate IDs")
        ready[key] = (row, payload, checks)
    if not ready:
        raise ValueError("No current, approved calendar-period candidates selected")
    published = []
    with store.transaction() as c:
        existing = c.execute("SELECT scope,period_end FROM ingest_heads WHERE org_id=? AND standard='MSFO'", (org,)).fetchall()
        # Once an issuer has snapshot heads the reader stops mixing legacy
        # figures into them. Refuse a partial first migration that hides years.
        if not existing:
            legacy = c.execute("SELECT DISTINCT year FROM catalog_financials WHERE form='MSFO' AND quarter=0 "
                               "AND ticker IN (SELECT ticker FROM catalog_companies WHERE org_id=?)", (org,)).fetchall()
            scope = "consolidated" if any(k[2] == "consolidated" for k in ready) else "separate"
            selected_years = {int(k[4][:4]) for k in ready if k[2] == scope and k[4][5:] == "12-31"}
            if {r["year"] for r in legacy} - selected_years:
                raise ValueError("First publication must include every legacy IFRS year in the selected perimeter")
        for key, (row, payload, checks) in ready.items():
            current = c.execute("SELECT latest_version FROM ingest_sources WHERE id=?", (row["source_id"],)).fetchone()
            if current["latest_version"] != row["version_id"]:
                raise ValueError("Source changed while publication was being prepared")
            snapshot_id = store.digest([row["id"], "snapshot-v1"])
            old = c.execute("SELECT snapshot_id FROM ingest_heads WHERE org_id=? AND standard=? AND scope=? AND period_start=? AND period_end=?", key).fetchone()
            if old and old["snapshot_id"] != snapshot_id and not replace:
                raise ValueError("Replacing published figures requires explicit revision approval")
            if old and old["snapshot_id"] == snapshot_id:
                published.append(snapshot_id)
                continue
            source_policy.require(row['url'])
            source_meta = json.loads(row["metadata_json"])
            full = {**payload, "normalized_uzs": checks["normalized_uzs"], "warnings": checks["warnings"],
                    "source": {"file_hash": row["sha"], "pdf_url": row["url"], "category": row["category"],
                               "received_at": row["received_at"], "source_published_at": source_meta.get("published_at"),
                               "candidate_id": row["id"], "extraction_version": row["processor"], "review_id": row["review_id"]}}
            c.execute("INSERT INTO ingest_snapshots VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                      (snapshot_id, row["id"], row["review_id"], *key, store.encoded(full), store.now()))
            c.execute("INSERT INTO ingest_heads VALUES (?,?,?,?,?,?) ON CONFLICT(org_id,standard,scope,period_start,period_end) "
                      "DO UPDATE SET snapshot_id=excluded.snapshot_id", (*key, snapshot_id))
            store.event(c, snapshot_id, "snapshot.published", actor=actor,
                        previous=old["snapshot_id"] if old else None, candidate=row["id"])
            published.append(snapshot_id)
    return {"ticker": ticker, "published": len(published), "snapshots": published}


def rollback(snapshot_id, *, actor, reason):
    if not actor or not reason:
        raise ValueError("Rollback actor and reason are required")
    with store.transaction() as c:
        target = c.execute("SELECT * FROM ingest_snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if not target:
            raise ValueError("Unknown snapshot")
        key = tuple(target[k] for k in ("org_id", "standard", "scope", "period_start", "period_end"))
        head = c.execute("SELECT snapshot_id FROM ingest_heads WHERE org_id=? AND standard=? AND scope=? AND period_start=? AND period_end=?", key).fetchone()
        if not head:
            raise ValueError("No publication to roll back")
        c.execute("UPDATE ingest_heads SET snapshot_id=? WHERE org_id=? AND standard=? AND scope=? AND period_start=? AND period_end=?", (snapshot_id, *key))
        store.event(c, snapshot_id, "snapshot.rollback", actor=actor, previous=head["snapshot_id"], reason=reason)


def snapshots(ticker, *, scope=None):
    """Read one perimeter, defaulting to the newest with consolidated as tie-break."""
    if scope not in {None, "separate", "consolidated"}:
        raise ValueError("Unknown accounting scope")
    import reports_catalog as rc
    # No schema creation/read takeover until the worker has initialized it.
    import dbx
    c = rc.get_catalog_conn()
    try:
        if "ingest_heads" not in dbx.tables(c):
            return []
        rows = c.execute("SELECT p.* FROM ingest_heads h JOIN ingest_snapshots p ON p.id=h.snapshot_id "
                         "WHERE h.org_id=(SELECT org_id FROM catalog_companies WHERE ticker=?) AND h.standard='MSFO'",
                         (ticker.upper(),)).fetchall()
        selected_scope = scope or (max(rows, key=lambda r: (r["period_end"], r["scope"] == "consolidated"))["scope"] if rows else "separate")
        return [{**dict(r), "payload": json.loads(r["payload_json"])} for r in rows if r["scope"] == selected_scope]
    finally:
        c.close()


def scopes(ticker):
    """Published accounting scopes, independent of period/frequency selection."""
    return [scope for scope in ("consolidated", "separate") if snapshots(ticker, scope=scope)]


def series(ticker, *, quarterly=False, scope=None):
    rows = snapshots(ticker, scope=scope)
    if not rows:
        return None
    return {period_key(row["payload"]["classification"]): {field: float(Decimal(value) / 1000)
            for field, value in row["payload"]["normalized_uzs"].items()} for row in rows
            if ("Q" in (period_key(row["payload"]["classification"]) or "")) == quarterly}


def latest(ticker):
    """One snapshot-based read model for calculation consumers, in thousands UZS."""
    rows = snapshots(ticker)
    if not rows:
        return None
    def convert(row):
        meta = row["payload"]["classification"]
        period = period_key(meta)
        quarter = int(period[-1]) if "Q" in period else 0
        values = {f: float(Decimal(v) / 1000) for f, v in row["payload"]["normalized_uzs"].items()}
        return {**values, "year": int(period[:4]), "quarter": quarter, "is_ytd": bool(quarter),
                "period_months": quarter * 3 if quarter else 12, "org_type": "bank", "standard": "MSFO",
                "balance": {"assets_end": values.get("total_assets"), "equity_end": values.get("total_equity")},
                "field_periods": {}, "report_id": None, "snapshot_id": row["id"],
                "scope": meta["scope"], "updated_at": row["created_at"]}
    ordered = sorted(rows, key=lambda r: r["period_end"], reverse=True)
    result = convert(ordered[0])
    annual = next((r for r in ordered if r["period_end"][5:] == "12-31"), None)
    if result["quarter"] and annual:
        result["annual"] = convert(annual)
    prior = next((r for r in ordered if int(r["period_end"][:4]) == result["year"] - 1
                  and r["period_end"][5:] == ordered[0]["period_end"][5:]), None)
    if prior:
        result["prior"] = convert(prior)
    return result


def catalog_labels(ticker):
    """Only PRIMARY published evidence can correct a catalog document's period."""
    labels = {}
    rows = snapshots(ticker)
    if not rows:
        return labels
    c = store.connect()
    try:
        current = {r["id"] for r in c.execute(
            "SELECT x.id FROM ingest_candidates x JOIN ingest_versions v ON v.id=x.version_id "
            "JOIN ingest_sources s ON s.latest_version=v.id")}
    finally:
        c.close()
    for row in rows:
        meta = row["payload"]["classification"]
        if meta["role"] != "PRIMARY" or row["candidate_id"] not in current:
            continue
        period = period_key(meta)
        labels[row["payload"]["source"]["pdf_url"]] = {
            "year": int(period[:4]), "quarter": int(period[-1]) if "Q" in period else 0,
            "period_type": "quarter" if "Q" in period else "annual",
            "scope": meta["scope"], "verified": True, "snapshot_id": row["id"],
        }
    return labels


def passport(ticker, period, field, *, scope=None):
    rows = snapshots(ticker, scope=scope)
    if not rows:
        if scope is not None:
            return {"status": "NO_DATA", "standard": "MSFO", "period": period, "field": field,
                    "scope": scope, "reason": "No published figures in the requested accounting scope"}
        return None
    key = {"net_profit": "net_income", "net_revenue": "revenue"}.get(field, field)
    row = next((r for r in rows if period_key(r["payload"]["classification"]) == period), None)
    if not row or key not in row["payload"]["figures"]:
        return {"status": "NO_DATA", "standard": "MSFO", "period": period, "field": field,
                "reason": "No approved snapshot figure exists for this period and perimeter"}
    payload = row["payload"]
    figure, meta = payload["figures"][key], payload["classification"]
    source = payload["source"]
    amount = Decimal(figure["raw_value"])
    return {"status": "SOURCED", "period": period, "field": field, "standard": "MSFO", "source_field": key,
            "value": float(Decimal(payload["normalized_uzs"][key]) / 1000),
            "source": {**source, "snapshot_id": row["id"], "state": "published", "standard": "MSFO", "report_form": "MSFO",
                       "perimeter": meta["scope"], "scope": meta["scope"], "period_type": "quarter" if "Q" in period else "annual", "period_year": meta["document_year"],
                       "period_start": meta["period_start"], "period_end": meta["period_end"], "period_basis": "cumulative_ytd" if "Q" in period else "annual",
                       "calculation": figure.get("calculation"), "components": figure.get("components"),
                       "stated_period": period, "role": meta["role"], "published_at": row["created_at"],
                       "title": f"{meta.get('issuer_name', ticker)} — IFRS {meta['document_year']} ({meta['scope']})",
                       "page": figure["page"], "raw_label": figure["raw_label"], "raw_value": float(amount),
                       "unit_scale": int(meta["unit_scale"]), "normalized_value": float(payload["normalized_uzs"][key]),
                       "normalization_formula": ("sum(coefficient × source component) × unit_scale"
                                                 if figure.get("calculation") == "signed_sum" else
                                                 "sum(source components) × unit_scale" if figure.get("components") else
                                                 "raw_value × unit_scale"),
                       "sign": "negative" if amount < 0 else "zero" if not amount else "positive",
                       "archived_url": f"/api/company/{ticker}/financials/documents/{source['file_hash']}"}}
