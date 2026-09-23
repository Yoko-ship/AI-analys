"""Read-only inventory for bulk parsing and evidence-based follow-up work.

Coverage describes registered evidence, never proof of complete issuer history.
No approval, publication, or source-policy changes are performed here.
"""
from collections import Counter, defaultdict
from datetime import date
import json

from . import extract, publication, source_policy, store


COMMON_FIELDS = {"cash", "total_assets", "total_liabilities", "total_equity", "net_income"}
BANK_FIELDS = COMMON_FIELDS | {"interest_income", "interest_expense", "operating_income", "operating_expenses"}
COMPANY_FIELDS = COMMON_FIELDS | {"revenue"}


def _annual_gaps(periods):
    """Only interior calendar years, separately for each standard and scope."""
    groups = defaultdict(set)
    for meta in periods:
        try:
            start = date.fromisoformat(meta.get("period_start") or "")
            end = date.fromisoformat(meta.get("period_end") or "")
        except (ValueError, TypeError):
            continue
        if (start.year == end.year and start.month == start.day == 1
                and (end.month, end.day) == (12, 31)
                and meta.get("scope") in {"separate", "consolidated"}
                and meta.get("standard") in {"MSFO", "NSBU"}):
            groups[(meta["standard"], meta["scope"])].add(start.year)
    return [{"standard": standard, "scope": scope,
             "observed_start": min(years), "observed_end": max(years),
             "missing_years": sorted(set(range(min(years), max(years) + 1)) - years)}
            for (standard, scope), years in sorted(groups.items())]


def build_report(tickers=None):
    """Return a JSON-safe issuer/source manifest, including sibling tickers.

    ``None`` includes every catalog issuer. An explicit empty list includes none;
    unknown tickers are reported rather than silently broadening the selection.
    Current parser candidates and explicit reviewed proposals are distinguished.
    """
    requested = None if tickers is None else {str(t).strip().upper() for t in tickers if str(t).strip()}
    processor = extract.processor_version()
    c = store.connect()
    try:
        # A single read transaction gives every count the same database snapshot.
        c.execute("BEGIN")
        companies = [dict(r) for r in c.execute("SELECT ticker,company_name,org_id FROM catalog_companies").fetchall()]
        sources = [dict(r) for r in c.execute("SELECT * FROM ingest_sources ORDER BY org_id,url").fetchall()]
        versions = {r["id"]: dict(r) for r in c.execute("SELECT id,sha FROM ingest_versions").fetchall()}
        candidates = [dict(r) for r in c.execute("SELECT * FROM ingest_candidates ORDER BY created_at,id").fetchall()]
        reviews = [dict(r) for r in c.execute("SELECT candidate_id,decision FROM ingest_reviews").fetchall()]
        snapshots = [dict(r) for r in c.execute("SELECT id,candidate_id FROM ingest_snapshots").fetchall()]
        heads = [dict(r) for r in c.execute("SELECT * FROM ingest_heads").fetchall()]
        jobs = [dict(r) for r in c.execute("SELECT id,source_id,stage,state,error,available_at FROM ingest_jobs").fetchall()]
        disclosures = [dict(r) for r in c.execute("SELECT * FROM ingest_disclosures ORDER BY org_id,api_path").fetchall()]
        banks = {str(r["org_id"]) for r in c.execute(
            "SELECT DISTINCT c.org_id FROM catalog_companies c JOIN catalog_reports r ON r.ticker=c.ticker "
            "WHERE r.report_form='NSBU' AND (r.excel_url LIKE '%org_type=bank%' "
            "OR r.excel_url_form1 LIKE '%org_type=bank%')").fetchall()}
    finally:
        c.close()

    groups = defaultdict(list)
    for company in companies:
        org = str(company["org_id"] or "").strip()
        groups[org or "unresolved:" + company["ticker"]].append(company)
    known = {r["ticker"] for r in companies}
    by_source, by_org, by_version, decisions = (defaultdict(list) for _ in range(4))
    for row in jobs:
        by_source[row["source_id"]].append(row)
    for row in sources:
        by_org[row["org_id"]].append(row)
    for row in candidates:
        by_version[row["version_id"]].append(row)
    for row in reviews:
        decisions[row["candidate_id"]].append(row["decision"])
    ever_published = {r["candidate_id"] for r in snapshots}
    snapshot_candidates = {r["id"]: r["candidate_id"] for r in snapshots}
    current_heads = {snapshot_candidates.get(r["snapshot_id"]) for r in heads}
    issuers = []
    totals = Counter({name: 0 for name in (
        "issuers", "issuers_without_sources", "active_sources", "retained_sources",
        "candidates", "candidates_missing_fields", "invalid_candidates", "approved_unpublished",
        "unreviewed_candidates", "failed_jobs", "discovery_errors")})
    for key, members in sorted(groups.items()):
        aliases = sorted(r["ticker"] for r in members)
        if requested is not None and not requested.intersection(aliases):
            continue
        ticker = sorted(aliases, key=lambda t: (t.endswith("P") and t[:-1] in aliases, t))[0]
        org = str(members[0]["org_id"] or "").strip() or None
        issuer_sources, periods = [], []
        for source in by_org.get(org, []):
            active = source_policy.allows(source["url"])
            latest_candidates = by_version.get(source["latest_version"], [])
            is_bank = org in banks or any(
                {"interest_income", "interest_expense"}.intersection(json.loads(r["payload_json"]).get("figures") or {})
                for r in latest_candidates)
            expected = sorted(BANK_FIELDS if is_bank else COMPANY_FIELDS)
            entries = []
            for row in latest_candidates:
                payload, checks = json.loads(row["payload_json"]), json.loads(row["checks_json"])
                meta, figures = payload.get("classification") or {}, payload.get("figures") or {}
                approved = "APPROVED" in decisions[row["id"]]
                current = row["processor"] == processor
                reviewed = row["processor"] == "reviewed-proposal-v1"
                # Older parser drafts cannot masquerade as current extraction.
                if not current and not reviewed and not approved and row["id"] not in ever_published:
                    continue
                missing = [field for field in expected if not isinstance(figures.get(field), dict)
                           or figures[field].get("raw_value") is None]
                entry = {"candidate_id": row["id"], "processor": row["processor"],
                         "current_processor": current, "reviewed_proposal": reviewed,
                         "classification": meta, "period": publication.period_key(meta),
                         "expected_fields": expected, "missing_fields": missing,
                         "validation_valid": bool(checks.get("valid")),
                         "validation_errors": checks.get("errors") or [],
                         "validation_warnings": checks.get("warnings") or [],
                         "review_decisions": sorted(set(decisions[row["id"]])),
                         "review_state": "APPROVED" if approved else "REVIEWED" if decisions[row["id"]] else "UNREVIEWED",
                         "published_current": row["id"] in current_heads,
                         "published_ever": row["id"] in ever_published,
                         "approved_unpublished": approved and row["id"] not in ever_published}
                entries.append(entry)
                if active and (current or reviewed):
                    periods.append(meta)
                    totals["candidates"] += 1
                    totals["candidates_missing_fields"] += bool(missing)
                    totals["invalid_candidates"] += not entry["validation_valid"]
                if active:
                    totals["approved_unpublished"] += entry["approved_unpublished"]
                    totals["unreviewed_candidates"] += entry["review_state"] == "UNREVIEWED"
            source_jobs = by_source[source["id"]]
            failures = [{**j, "url": source["url"]} for j in source_jobs
                        if j["state"] in {"FAILED", "RETRY"} and j["error"]]
            issuer_sources.append({"source_id": source["id"], "url": source["url"],
                                   "category": source["category"], "active_policy": active,
                                   "version_id": source["latest_version"],
                                   "sha256": versions.get(source["latest_version"], {}).get("sha"),
                                   "no_version": not bool(source["latest_version"]),
                                   "no_candidates": not bool(latest_candidates),
                                   "no_current_candidates": not any(r["processor"] == processor for r in latest_candidates),
                                   "jobs": dict(Counter(j["state"] for j in source_jobs)),
                                   "failures": failures, "candidates": entries})
            totals["active_sources" if active else "retained_sources"] += 1
            if active:
                totals["failed_jobs"] += sum(j["state"] == "FAILED" for j in source_jobs)
        active_sources = [s for s in issuer_sources if s["active_policy"]]
        errors = [{"disclosure_id": r["id"], "url": "https://new-api.openinfo.uz/api/v2" + r["api_path"],
                   "reason": r["error"], "retry_at": r["retry_at"]}
                  for r in disclosures if r["org_id"] == org and r["error"]]
        issuer = {"org_id": org, "ticker": ticker, "tickers": aliases,
                  "company_name": next(r["company_name"] for r in members if r["ticker"] == ticker),
                  "unresolved_issuer": org is None, "no_sources": not bool(active_sources),
                  "sources": issuer_sources, "discovery_errors": errors,
                  "candidate_annual_ranges": _annual_gaps(periods),
                  "published_annual_ranges": _annual_gaps(r for r in heads if r["org_id"] == org)}
        issuers.append(issuer)
        totals["issuers"] += 1
        totals["issuers_without_sources"] += issuer["no_sources"]
        totals["discovery_errors"] += len(errors)
    return {"generated_at": store.now(), "processor": processor,
            "source_policy": source_policy.name(), "publication_performed": False,
            "coverage_basis": "Registered latest source versions; annual gaps only inside each observed standard/scope range. No claim of complete history.",
            "unknown_tickers": sorted((requested or set()) - known),
            "summary": dict(totals), "issuers": issuers}
