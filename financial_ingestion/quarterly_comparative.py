"""Recover quarterly figures from official structured filings and comparisons.

Keep comparisons separate from original filings. A quarterly opening balance
is January's balance, so it cannot supply the prior year's quarter-end stocks.
"""
from __future__ import annotations

import json
import math
import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import catalogue.fields as fields
import catalogue.storage as storage
import dbx

INCOME = ("revenue", "gross_profit", "net_income", "operating_income")


def _schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS catalog_comparative_quarters (
        ticker TEXT NOT NULL, year INTEGER NOT NULL, quarter INTEGER NOT NULL,
        values_json TEXT NOT NULL, source_json TEXT NOT NULL,
        PRIMARY KEY(ticker, year, quarter))""")
    c.execute("""CREATE TABLE IF NOT EXISTS catalog_structured_quarters (
        ticker TEXT NOT NULL, year INTEGER NOT NULL, quarter INTEGER NOT NULL,
        values_json TEXT NOT NULL, source_json TEXT NOT NULL,
        PRIMARY KEY(ticker, year, quarter))""")
    c.commit()


def _connect():
    c = storage.get_catalog_conn()
    dbx.ensure_schema(c, "catalog-quarter-recovery-v1", _schema)
    return c


def read(tickers, *, structured=False):
    c = _connect()
    try:
        result = {}
        table = "catalog_structured_quarters" if structured else "catalog_comparative_quarters"
        for ticker in tickers:
            for row in c.execute(f"SELECT * FROM {table} WHERE ticker=?", (ticker,)):
                result[f"{row['year']}Q{row['quarter']}"] = {
                    "values": json.loads(row["values_json"]), "source": json.loads(row["source_json"])}
        return result
    finally:
        c.close()


def _save(aliases, year, quarter, values, source, *, structured=False):
    table = "catalog_structured_quarters" if structured else "catalog_comparative_quarters"
    c = _connect()
    try:
        with c:
            for ticker in aliases:
                c.execute(f"INSERT INTO {table} VALUES(?,?,?,?,?) "
                          "ON CONFLICT(ticker,year,quarter) DO UPDATE SET "
                          "values_json=excluded.values_json,source_json=excluded.source_json",
                          (ticker, year, quarter, json.dumps(values), json.dumps(source)))
    finally:
        c.close()


def _valid_values(values):
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values.values()):
        raise ValueError("Invalid recovered amount")
    values, problem = fields.usable_filing(values)
    return values if not problem or problem["code"] == "no_balance" else {}


def backfill(org_id, aliases, journal=None):
    import openinfo_reconcile as oi

    parser_version = hashlib.sha256(Path(__file__).read_bytes() + Path(oi.__file__).read_bytes()).hexdigest()
    c = _connect()
    try:
        placeholders = ",".join("?" for _ in aliases)
        reports = [dict(r) for r in c.execute(
            f"SELECT * FROM catalog_reports WHERE ticker IN ({placeholders}) "
            "AND report_form='NSBU' AND quarter BETWEEN 1 AND 3 ORDER BY published_at DESC", aliases)]
        originals = {}
        for row in c.execute(f"SELECT * FROM catalog_financials WHERE ticker IN ({placeholders}) "
                             "AND form='NSBU' AND quarter BETWEEN 1 AND 3", aliases):
            values, _ = fields.usable_filing(dict(row))
            originals.setdefault((row["year"], row["quarter"]), {}).update(
                {k: v for k, v in values.items() if k in INCOME and v is not None})
    finally:
        c.close()
    existing = read(aliases)
    structured = read(aliases, structured=True)
    filled, errors, seen, recovered = [], [], set(), []
    for report in reports:
        year, quarter = report["year"] - 1, report["quarter"]
        period = f"{year}Q{quarter}"
        if year < 2015 or (year, quarter) in seen:
            continue
        seen.add((year, quarter))
        have = originals.get((year, quarter), {})
        need_comparison = not all(have.get(k) is not None for k in INCOME)
        current_period = f"{year + 1}Q{quarter}"
        current = originals.get((year + 1, quarter), {})
        need_current = any(current.get(k) is None for k in ("revenue", "net_income"))
        params = parse_qs(urlparse(report.get("excel_url") or report.get("excel_url_form1") or "").query)
        org_type = (params.get("org_type") or [None])[0]
        object_id = report.get("object_id") or report.get("openinfo_report_id")
        if org_type not in oi.ORG_TYPES or not str(object_id or "").isdigit():
            continue
        source_url = f"https://openinfo.uz/reports/{org_type}/quarter/{object_id}"
        previous = existing.get(period, {})
        def matches(saved):
            source = saved.get("source", {})
            return (source.get("source_url") == source_url and source.get("pub_date") == report["published_at"]
                    and source.get("parser_version") == parser_version)
        need_comparison = need_comparison and org_type in {"jsc", "insurance"} and not matches(previous)
        need_current = need_current and not matches(structured.get(current_period, {}))
        if not need_comparison and not need_current:
            continue
        try:
            detail = oi.fetch_detail({"org_type": org_type, "period_type": "quarter", "object_id": int(object_id)})
            source_period = oi.period_year_quarter(detail.get("reporting_year"), "quarter",
                pub_date=detail.get("pub_date"), quarter_no=detail.get("quarter_no"))
            if (source_period != (report["year"], quarter) or detail.get("org_type") != org_type
                    or str(detail.get("id")) != str(object_id)):
                raise ValueError("Comparison source period or form does not match the catalog")
            metrics = oi.extract_metrics(detail)
            if need_current:
                values = {k: v for k, v in metrics.items() if k in fields.FIN_MONEY_FIELDS and v is not None}
                balance = metrics.get("balance") or {}
                for k, b in (("total_assets", "assets_end"), ("total_equity", "equity_end")):
                    if balance.get(b) is not None:
                        values[k] = balance[b]
                values = _valid_values(values)
                if values:
                    source = {"kind": "structured", "source_period": current_period,
                              "source_url": source_url, "pub_date": report["published_at"], "org_id": str(org_id), "parser_version": parser_version}
                    _save(aliases, year + 1, quarter, values, source, structured=True)
                    recovered.append(current_period)
                    if journal:
                        journal("year_backfill", ticker=aliases[0], standard="NSBU", period=current_period,
                                message=f"{current_period} from the official structured filing", source_url=source_url, details=source)
            if not need_comparison:
                continue
            values = {k: v for k, v in (metrics.get("prior") or {}).items() if k in INCOME and v is not None}
            values = _valid_values(values)
            if not values:
                continue
            # Retain the full column: originals take precedence at read time.
            source = {"kind": "comparative", "source_period": f"{year + 1}Q{quarter}",
                      "source_url": source_url, "pub_date": report["published_at"], "org_id": str(org_id), "parser_version": parser_version}
            _save(aliases, year, quarter, values, source)
            filled.append(period)
            if journal:
                journal("year_backfill", ticker=aliases[0], standard="NSBU", period=period,
                        message=f"{period} income from the next year's same-quarter comparison column",
                        source_url=source_url, details=source)
        except Exception as exc:
            errors.append({"ticker": aliases[0], "period": period, "stage": "quarter_comparative", "error": str(exc)})
    return {"filled": filled, "structured": recovered, "errors": errors}


def main(argv=None):
    """Run gap recovery for all catalog issuers without re-downloading workbooks."""
    import argparse
    from .nsbu_history import _issuers, _journal
    from .bulk import write_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", action="append")
    parser.add_argument("--report", default="data/quarterly-recovery-report.json")
    args = parser.parse_args(argv)
    results = []
    for org_id, aliases in _issuers(args.ticker):
        outcome = {"issuer": org_id, "tickers": aliases, **backfill(org_id, aliases, journal=_journal)}
        results.append(outcome)
        write_report(args.report, {"issuers": results})
        print(json.dumps(outcome), flush=True)
    return int(any(r["errors"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
