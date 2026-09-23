"""Resume all catalogued NSBU annual and quarterly workbooks in the shared DB.

Run after the catalog sync: python -m financial_ingestion.nsbu_history
This uses the existing national-accounting publication path, not IFRS review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
from pathlib import Path

import reports_catalog as rc
from . import store

log = logging.getLogger(__name__)
_REQUIRED = ("revenue", "gross_profit", "net_income", "operating_income",
             "cash", "total_assets", "total_equity", "total_liabilities", "operating_expenses")


def implementation_digest():
    digest = hashlib.sha256()
    # Includes helper/parser changes, rather than just the orchestration version.
    for path in (Path(__file__), Path(rc.__file__),
                 Path(rc.__file__).with_name("openinfo_collector.py"),
                 Path(rc.__file__).with_name("nsbu_periods.py"),
                 Path(rc.__file__).with_name("reviewed_nsbu_periods.json")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _connect():
    c = rc.get_catalog_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS nsbu_history_checkpoints (
        id TEXT PRIMARY KEY, issuer TEXT NOT NULL, year INTEGER NOT NULL,
        quarter INTEGER NOT NULL, source_json TEXT NOT NULL,
        implementation TEXT NOT NULL, status TEXT NOT NULL,
        payload_json TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.commit()
    return c


def _issuers(tickers):
    c = _connect()
    try:
        rows = [dict(r) for r in c.execute("SELECT ticker,org_id FROM catalog_companies ORDER BY ticker")]
    finally:
        c.close()
    requested = {t.strip().upper() for t in tickers or []}
    unknown = requested - {r["ticker"] for r in rows}
    if unknown:
        raise ValueError("Unknown tickers: " + ", ".join(sorted(unknown)))
    groups = {}
    for row in rows:
        groups.setdefault(str(row["org_id"] or "ticker:" + row["ticker"]), []).append(row["ticker"])
    return [(issuer, aliases) for issuer, aliases in groups.items()
            if not requested or requested.intersection(aliases)]


def _periods(aliases):
    c = rc.get_catalog_conn()
    try:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM catalog_reports WHERE ticker IN (" + ",".join("?" for _ in aliases) + ") "
            "AND report_form='NSBU' AND period_type IN ('annual','quarter') ORDER BY year,quarter", aliases)]
    finally:
        c.close()
    periods = {}
    for row in rows:
        if row["year"] and not rc._is_future_period(row["year"], row["quarter"]):
            periods.setdefault((row["year"], row["quarter"]), []).append(row)
    return periods


def _source(rows):
    # The issuer's latest revision with a workbook wins across share classes.
    source = max(rows, key=lambda r: (bool(r["excel_url"] or r["excel_url_form1"]),
                                     str(r["published_at"] or ""), r["id"]))
    fields = ("id", "ticker", "year", "quarter", "period_type", "openinfo_report_id",
              "excel_url", "excel_url_form1", "published_at")
    relationships = [{k: r[k] for k in fields} for r in sorted(rows, key=lambda r: r["id"])]
    return source, relationships


def _align_sources(aliases, source):
    fields = ("report_form", "period_type", "year", "quarter", "title", "published_at",
              "pdf_url", "excel_url", "excel_url_form1", "openinfo_report_id", "object_id")
    c = rc.get_catalog_conn()
    try:
        with c:
            for alias in aliases:
                rc._upsert_report(c, alias, **{k: source[k] for k in fields})
                # The chosen source is known: remove obsolete sibling URLs too.
                c.execute("UPDATE catalog_reports SET excel_url=?,excel_url_form1=?,pdf_url=?,"
                          "openinfo_report_id=?,object_id=?,published_at=? WHERE ticker=? "
                          "AND report_form='NSBU' AND period_type=? AND year=? AND quarter=?",
                          (source["excel_url"], source["excel_url_form1"], source["pdf_url"],
                           source["openinfo_report_id"], source["object_id"], source["published_at"],
                           alias, source["period_type"], source["year"], source["quarter"]))
    finally:
        c.close()


def _validate_replacement(aliases, year, quarter, values):
    for field in rc.FIN_MONEY_FIELDS:
        value = values.get(field)
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("Invalid financial value: " + field)
    c = rc.get_catalog_conn()
    try:
        for alias in aliases:
            row = c.execute("SELECT * FROM catalog_financials WHERE ticker=? AND form='NSBU' AND year=? AND quarter=?",
                            (alias, year, quarter)).fetchone()
            if row:
                lost = [k for k in rc._FINANCIAL_KEYS + ("total_assets", "total_equity")
                        if row[k] is not None and values.get(k) is None]
                if lost:
                    raise ValueError("Incomplete parse would erase existing fields: " + ", ".join(lost))
    finally:
        c.close()


def _checkpoint_matches(c, key, aliases, year, quarter):
    checkpoint = c.execute("SELECT status,payload_json FROM nsbu_history_checkpoints WHERE id=?", (key,)).fetchone()
    if not checkpoint or checkpoint["status"] != "complete":
        return False
    payload = json.loads(checkpoint["payload_json"])
    for ticker in aliases:
        row = c.execute("SELECT * FROM catalog_financials WHERE ticker=? AND form='NSBU' AND year=? AND quarter=?",
                        (ticker, year, quarter)).fetchone()
        if not row or not row["report_id"] or row["report_id"] != payload["report_id"]:
            return False
        # A later seed/enrichment or lost cache row must not be hidden by a checkpoint.
        for field in rc._FIN_FIELDS + rc._FIN_CURRENT_FIELDS:
            expected = payload["values"].get(field)
            # The existing cache writer deliberately preserves optional current
            # assets from another form when absent in a bank statement.
            if expected is None and field in rc._FIN_CURRENT_FIELDS:
                continue
            if row[field] != expected:
                return False
    return True


def run(tickers=None, force=False, max_periods=None):
    if max_periods is not None and max_periods < 0:
        raise ValueError("max_periods must be nonnegative")
    implementation = implementation_digest()
    result = {"processed": 0, "complete": 0, "partial": 0, "skipped": 0,
              "discovered": 0, "errors": [], "stopped_by_budget": False}
    for issuer, aliases in _issuers(tickers):
        if max_periods is not None and result["processed"] >= max_periods:
            result["stopped_by_budget"] = True
            break
        ticker = rc._canonical_ticker(aliases)
        try:
            discovery = rc.harvest_historical_quarters(ticker, limit=1000, publish=False)
            result["discovered"] += discovery.get("added", 0)
            result["errors"].extend({"ticker": ticker, "stage": "discovery", "error": str(e)}
                                    for e in discovery.get("errors", []))
        except Exception as exc:
            result["errors"].append({"ticker": ticker, "stage": "discovery", "error": str(exc)})
        for (year, quarter), rows in _periods(aliases).items():
            source, relationships = _source(rows)
            key = store.digest([issuer, year, quarter, relationships, implementation, aliases])
            c = _connect()
            try:
                skip = not force and _checkpoint_matches(c, key, aliases, year, quarter)
            finally:
                c.close()
            if skip:
                result["skipped"] += 1
                continue
            if max_periods is not None and result["processed"] >= max_periods:
                result["stopped_by_budget"] = True
                break
            result["processed"] += 1
            status, payload = "error", {}
            try:
                data = rc.fetch_report_excel_data(source["ticker"], "NSBU", year, quarter,
                                                 use_snapshot_cache=False)
                ratios = rc.compute_financial_ratios(data.get("income"), data.get("balance")) if data.get("ok") else {}
                values = ratios.get("source_values") or {}
                values["total_equity"] = values.get("total_equity", values.get("equity"))
                if not data.get("ok") or not any(values.get(k) is not None for k in rc.FIN_MONEY_FIELDS):
                    raise ValueError(data.get("error") or "No usable financial indicators")
                current = _periods(aliases).get((year, quarter), [])
                if not current or _source(current)[1] != relationships:
                    raise ValueError("Source mapping changed during extraction; retry next run")
                _validate_replacement(aliases, year, quarter, values)
                _align_sources(aliases, source)
                report_id = rc._register_parse(source["ticker"], "NSBU", year, quarter, data, values)
                relationships = _source(_periods(aliases)[(year, quarter)])[1]
                key = store.digest([issuer, year, quarter, relationships, implementation, aliases])
                # Readers prefer the requested ticker over siblings. Refresh every
                # alias so an old preferred-share row cannot override this repair.
                for alias in aliases:
                    rc.upsert_financials_cache(alias, "NSBU", year, quarter, values, report_id)
                    rc.upsert_ratio_cache(alias, "NSBU", year, quarter, ratios.get("metrics") or {})
                missing = [field for field in _REQUIRED if values.get(field) is None]
                status = "complete" if not missing and not data.get("warnings") and report_id else "partial"
                payload = {"values": values, "report_id": report_id, "missing": missing,
                           "warnings": data.get("warnings", [])}
                result[status] += 1
            except Exception as exc:
                payload = {"error": str(exc)}
                result["errors"].append({"ticker": ticker, "year": year, "quarter": quarter, "error": str(exc)})
                log.warning("NSBU %s %s Q%s: %s", ticker, year, quarter, exc)
            c = _connect()
            try:
                with c:
                    c.execute("INSERT INTO nsbu_history_checkpoints VALUES (?,?,?,?,?,?,?,?,?) "
                              "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                              "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                              (key, issuer, year, quarter, store.encoded(relationships), implementation,
                               status, store.encoded(payload), store.now()))
            finally:
                c.close()
            log.info("NSBU %s %s Q%s: %s (%d processed)", ticker, year, quarter, status, result["processed"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", action="append")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-periods", type=int)
    parser.add_argument("--report", default="data/nsbu-history-report.json")
    args = parser.parse_args(argv)
    if args.max_periods is not None and args.max_periods < 0:
        parser.error("--max-periods must be nonnegative")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = run(args.ticker, args.force, args.max_periods)
    from .bulk import write_report
    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
