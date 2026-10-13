"""Refile NSBU quarterly workbooks the history import put in the wrong year.

Until 2026-10-13 the history import dated a quarterly filing by its publication
day alone, which assumes a filing is less than a year late. UQEQ disclosed its
2021 half-year on 2022-09-14 and it was catalogued as 2022Q2: the 2021 chain
lost its half-year, and the 2022 chain gained a half-year larger than its own
nine months, so three quarters went blank behind data-quality notices.

The workbook header states the period outright («Период квартала», «Дата
отчетности»). This reads it for every catalogued quarterly workbook, and with
--apply moves each filing whose header disagrees with its label: the catalog
row goes to the stated period, and the figures and source passport the wrong
period was built from are removed. The NSBU history pass then re-parses the
moved filing and rediscovers any genuine filing the misfiled one displaced.

    python -m financial_ingestion.period_repair [--ticker UQEQ]          # dry run
    python -m financial_ingestion.period_repair [--ticker UQEQ] --apply
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import time
from typing import Any

import catalogue.history as catalogue_history
import catalogue.periods as catalogue_periods
import catalogue.sources as catalogue_sources
import catalogue.storage as catalogue_storage

log = logging.getLogger(__name__)


def stated_period(parsed: dict[str, Any], published_at: str | None) -> tuple[int, int] | None:
    """The (year, quarter) a workbook's own header places it in, or None.

    Both header lines are required: a quarter guessed from a publication month
    is exactly the kind of label this repair must not act on.
    """
    quarter = catalogue_periods._stated_quarter(parsed)
    stated = catalogue_periods._stated_reporting_date(parsed)
    if not quarter or not stated:
        return None
    try:
        pub = datetime.fromisoformat(str(published_at).replace("Z", "+00:00")) if published_at else None
    except ValueError:
        pub = None
    return catalogue_periods._quarter_period_from_publication(quarter, pub, stated)


def _catalogued(tickers: list[str] | None) -> list[dict[str, Any]]:
    conn = catalogue_storage.get_catalog_conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, ticker, year, quarter, published_at, openinfo_report_id, "
            "COALESCE(excel_url, excel_url_form1) AS excel FROM catalog_reports "
            "WHERE report_form='NSBU' AND period_type='quarter' AND quarter BETWEEN 1 AND 4 "
            "AND COALESCE(excel_url, excel_url_form1) IS NOT NULL ORDER BY ticker, year, quarter")]
    finally:
        conn.close()
    wanted = {t.strip().upper() for t in tickers or []}
    return [r for r in rows if not wanted or r["ticker"] in wanted]


def scan(tickers: list[str] | None = None, *, session: Any | None = None,
         pace: float = 0.2) -> dict[str, Any]:
    """Every catalogued quarterly workbook whose header names another period."""
    rows = _catalogued(tickers)
    session = session or catalogue_sources._make_session()
    by_url: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_url.setdefault(row["excel"], []).append(row)
    misfiled: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    for n, (url, group) in enumerate(by_url.items(), 1):
        try:
            parsed = catalogue_history._parse_workbook_uncached(session, url)
        except Exception as exc:  # noqa: BLE001 — one bad workbook is not the scan
            parsed = {"ok": False, "error": str(exc)}
        if not parsed.get("ok"):
            unreadable.extend({"ticker": r["ticker"], "period": f"{r['year']}Q{r['quarter']}",
                               "error": str(parsed.get("error"))} for r in group)
        else:
            for row in group:
                stated = stated_period(parsed, row["published_at"])
                if stated is None:
                    unreadable.append({"ticker": row["ticker"], "period": f"{row['year']}Q{row['quarter']}",
                                       "error": "header states no period"})
                elif stated != (row["year"], row["quarter"]):
                    misfiled.append({**row, "to_year": stated[0], "to_quarter": stated[1],
                                     "reporting_date": parsed.get("reporting_date")})
        if n % 100 == 0:
            log.info("period repair: %d/%d workbooks read, %d misfiled", n, len(by_url), len(misfiled))
        if pace:
            time.sleep(pace)
    return {"workbooks": len(by_url), "rows": len(rows), "misfiled": misfiled, "unreadable": unreadable}


def refile(misfiled: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Move each misfiled catalog row to its stated period and clear what it built.

    Where the stated period already holds a filing, the later publication wins,
    as it does for a revision anywhere else in the catalogue. The period the row
    leaves loses its figures, ratios and source passport: they were read from a
    workbook about another period, and the history pass rebuilds them from the
    genuine filing if openinfo has one.
    """
    done = []
    conn = catalogue_storage.get_catalog_conn()
    try:
        for m in misfiled:
            with conn:
                row = conn.execute("SELECT * FROM catalog_reports WHERE id=?", (m["id"],)).fetchone()
                if not row or (row["year"], row["quarter"]) != (m["year"], m["quarter"]):
                    continue  # moved by an earlier entry or a concurrent sync
                row = dict(row)
                target = conn.execute(
                    "SELECT id, published_at FROM catalog_reports WHERE ticker=? AND report_form='NSBU' "
                    "AND period_type='quarter' AND year=? AND quarter=?",
                    (row["ticker"], m["to_year"], m["to_quarter"])).fetchone()
                if target is None:
                    conn.execute("UPDATE catalog_reports SET year=?, quarter=? WHERE id=?",
                                 (m["to_year"], m["to_quarter"], row["id"]))
                    action = "moved"
                else:
                    if str(row["published_at"] or "") > str(target["published_at"] or ""):
                        conn.execute(
                            "UPDATE catalog_reports SET title=?, published_at=?, pdf_url=?, excel_url=?, "
                            "excel_url_form1=?, openinfo_report_id=?, object_id=? WHERE id=?",
                            (row["title"], row["published_at"], row["pdf_url"], row["excel_url"],
                             row["excel_url_form1"], row["openinfo_report_id"], row["object_id"], target["id"]))
                        action = "replaced_older_revision"
                    else:
                        action = "dropped_older_revision"
                    conn.execute("DELETE FROM catalog_reports WHERE id=?", (row["id"],))
                key = (row["ticker"], m["year"], m["quarter"])
                conn.execute("DELETE FROM catalog_financials WHERE ticker=? AND form='NSBU' AND year=? AND quarter=?", key)
                conn.execute("DELETE FROM catalog_ratios WHERE ticker=? AND form='NSBU' AND year=? AND quarter=?", key)
                org = conn.execute("SELECT org_id FROM catalog_companies WHERE ticker=?", (row["ticker"],)).fetchone()
                org_id = str((org["org_id"] if org else None) or f"ticker:{row['ticker']}")
                for stale in conn.execute(
                        "SELECT id FROM source_reports WHERE org_id=? AND report_form='NSBU' "
                        "AND period_type='quarter' AND period_year=? AND period_quarter=?",
                        (org_id, m["year"], m["quarter"])).fetchall():
                    conn.execute("DELETE FROM report_figures WHERE report_id=?", (stale["id"],))
                    conn.execute("DELETE FROM source_reports WHERE id=?", (stale["id"],))
            done.append({"ticker": row["ticker"], "from": f"{m['year']}Q{m['quarter']}",
                         "to": f"{m['to_year']}Q{m['to_quarter']}", "action": action,
                         "openinfo_report_id": row["openinfo_report_id"],
                         "reporting_date": m.get("reporting_date"), "published_at": row["published_at"]})
    finally:
        conn.close()
    return done


def run(tickers: list[str] | None = None, apply: bool = False, pace: float = 0.2) -> dict[str, Any]:
    found = scan(tickers, pace=pace)
    report: dict[str, Any] = {"workbooks": found["workbooks"], "rows": found["rows"],
                              "misfiled": [{"ticker": m["ticker"], "from": f"{m['year']}Q{m['quarter']}",
                                            "to": f"{m['to_year']}Q{m['to_quarter']}",
                                            "openinfo_report_id": m["openinfo_report_id"],
                                            "reporting_date": m["reporting_date"],
                                            "published_at": m["published_at"]} for m in found["misfiled"]],
                              "unreadable": found["unreadable"], "applied": False}
    if apply and found["misfiled"]:
        report["refiled"] = refile(found["misfiled"])
        report["applied"] = True
        from . import nsbu_history
        affected = sorted({m["ticker"] for m in found["misfiled"]})
        report["history"] = nsbu_history.run(affected)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", action="append")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--pace", type=float, default=0.2)
    parser.add_argument("--report", default="data/period-repair-report.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = run(args.ticker, args.apply, args.pace)
    from .bulk import write_report
    write_report(args.report, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"unreadable", "history"}},
                     ensure_ascii=False, indent=2))
    print(f"unreadable: {len(report['unreadable'])}; full report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
