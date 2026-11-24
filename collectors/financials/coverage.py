"""Compare public screener metrics with calculations over the versioned catalogue."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

import requests
from urllib3.util.retry import Retry

from financial_analysis.report_investor_metrics import SHARE_METRICS
from financial_ingestion.store import encoded

log = logging.getLogger("collector")
ANNUAL = ["assets", "equity", "net_profit", "revenue", "roa", "roe", "de", "pe", "pb", "ps", "ep", "cg3", "cg5", "dy", "price", "market_cap", "nim", "npl", "cost_of_risk"]
FILING = SHARE_METRICS | {"roce", "ebit", "issuer_price_to_book"}
SCOPES = ("separate", "consolidated")
NON_APPLICABLE = {
    "NOT_APPLICABLE",
    "ORDINARY_SHARES_ONLY",
    "SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE",
    "NON_POSITIVE_EQUITY",
    "NON_POSITIVE_PROFIT",
    "NON_POSITIVE_CAPITAL_EMPLOYED",
}
PROVENANCE = (
    "unit",
    "source_url",
    "page",
    "standard",
    "scope",
    "period_start",
    "market_as_of",
    "source_version",
)


def cell(item, period, *, reason=None):
    result = {"selected_period": period}
    reason = item.get("reason_code") or item.get("reason") or reason
    result["reason"] = reason if item.get("value") is None else None
    result["missing_inputs"] = sorted(item.get("missing_inputs") or [])
    for basis, source in (
        ("selected", item),
        ("earlier", item.get("last_verified") or {}),
        ("other_filing", item.get("other_filing") or {}),
    ):
        if source.get("value") is not None:
            value_period = source.get("period_end") or source.get("period") or period
            status = "current" if basis == "selected" else "earlier"
            if basis == "other_filing":
                from issuer_financials import period_end

                def end(s):
                    return s if s and "-" in str(s) else period_end(s)

                if not (
                    end(value_period)
                    and end(period)
                    and end(value_period) < end(period)
                ):
                    status = "other_filing"
            result.update(
                {k: source[k] for k in PROVENANCE if source.get(k) is not None}
            )
            result.update(
                status=status,
                basis=basis,
                period=value_period,
                value=source["value"],
            )
            return result
    na = reason in NON_APPLICABLE or "not_applicable" in (
        item.get("calculation_status"),
        item.get("quality"),
    )
    result["status"] = "inapplicable" if na else "gap"
    return result


def filing_cells(row, *, security=None, kind=None):
    security = security or {}
    bond = str(security.get("type", "")).lower() == "bond"
    ordinary_excluded = bond or security.get("is_preferred")
    metrics = row["metrics"]
    result = {}
    for key in sorted(FILING | metrics.keys()):
        reason = (
            row.get("status")
            if row.get("status") != "available"
            else "METRIC_UNAVAILABLE"
        )
        if (key in SHARE_METRICS and ordinary_excluded) or (key == "issuer_price_to_book" and bond):
            reason = "ORDINARY_SHARES_ONLY"
        if key == "ebit" and kind in {"bank", "insurance", "fund"}:
            reason = "NOT_APPLICABLE"
        result[key] = cell(
            metrics.get(key) or {},
            row.get("period"),
            reason=reason if key not in metrics else None,
        )
    return result


def annual_cells(row):
    from server.terminal.service import BANK_FIELDS

    result = {}
    period = row.get("period")
    extra = {f"cbu_{k}": group for group, fields in BANK_FIELDS.items() for k in fields}
    for key in [*ANNUAL, *extra]:
        source = {}
        date = period
        reason = (row.get("metric_reasons", {}).get(key) or {}).get("code")
        if key in extra or key == "npl":
            bank = (row.get("cbu") or {}).get(extra.get(key, "npl")) or {}
            source["source_url"] = bank.get("source_url")
            date = bank.get("date")
            if row.get("kind") != "bank":
                reason = "NOT_APPLICABLE"
        elif key == "dy":
            decision = (row.get("dividend") or {}).get("decision") or {}
            source["source_url"] = decision.get("source_url") or decision.get("link")
            date = decision.get("decision_date") or period
        elif key in {"market_cap", "price"}:
            date = row.get("market_date")
            reason = reason or (
                row.get("market_cap_reason")
                if key == "market_cap"
                else "PRICE_UNAVAILABLE"
            )
        elif key in {"ps", "revenue"} and row.get("kind") in {"bank", "fund"}:
            reason = "NOT_APPLICABLE"
        else:
            filing = row.get("source") or {}
            source["source_url"] = (
                filing.get("source_url")
                or filing.get("excel_url")
                or filing.get("pdf_url")
                if isinstance(filing, dict)
                else filing
            )
        if key in {"pe", "pb", "ps", "ep", "market_cap", "price", "dy"}:
            source["market_as_of"] = row.get("market_date")
        source["value"] = row.get(key)
        source["other_filing"] = (row.get("other_filing_metrics") or {}).get(key)
        if source["value"] is not None:
            reason = None
        result[key] = cell(
            source,
            date,
            reason=reason or (None if source["value"] is not None else "MISSING_INPUT"),
        )
        issues = [i.get("code") for i in row.get("issues", []) if i.get("code")]
        if issues:
            result[key]["filing_issues"] = sorted(set(issues))
    return result


def filing_rows(fetch, scope):
    seen = set()
    total = None
    while total is None or len(seen) < total:
        page = fetch("filing-metrics", scope=scope, offset=len(seen), limit=5)
        if total is None:
            total = page["total"]
        rows = page["rows"]
        if page["total"] != total or (not rows and len(seen) < total):
            raise ValueError("incomplete public filing pagination")
        for row in rows:
            if not row.get("ticker") or row["ticker"] in seen or len(seen) >= total:
                raise ValueError("incomplete or duplicated filing universe")
            seen.add(row["ticker"])
            yield row


def snapshot(fetch, companies):
    result = defaultdict(dict)
    for form, scope in (
        ("NSBU", "separate"),
        ("MSFO", "separate"),
        ("MSFO", "consolidated"),
    ):
        data = fetch("screener", form=form, scope=scope)
        if not data.get("ok") or data["standard"] != form or data["scope"] != scope:
            raise ValueError("incorrect annual screener context")
        view = f"annual:{form}:{scope}"
        for row in data["rows"]:
            t = row["ticker"]
            if view in result[t]:
                raise ValueError("duplicate annual issuer")
            result[t][view] = annual_cells(row)
    for scope in SCOPES:
        for row in filing_rows(fetch, scope):
            t = row["ticker"]
            result[t][f"filing:NSBU:{scope}"] = filing_cells(
                row, **companies.get(t, {})
            )
    return dict(result)


def verify_statement(native, public, prior):
    if prior is not None:
        observed = public()
        if observed == prior[1]:
            return prior[0], observed
    return native(), public()


def check_statements(db, expected, actual, versions, local, public):
    from functools import partial

    from .coverage_columns import statement_cells

    def read(fetch, ticker, form, scope, freq):
        path = f"/api/company/{ticker}/financials/columns"
        data = fetch(
            path,
            form=form,
            scope=scope,
            freq=freq,
            view="template",
            include_sources=False,
        )
        context = (ticker, form, scope, freq)
        if (
            not data.get("ok")
            or tuple(data.get(k) for k in ("ticker", "standard", "scope", "freq"))
            != context
        ):
            raise ValueError(f"incorrect company statement context {context}")
        return statement_cells(data)

    has_checkpoint = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='metric_coverage'"
    ).fetchone()
    for ticker in sorted(expected.keys() | actual.keys()):
        saved = None
        if has_checkpoint:
            saved = db.execute(
                "SELECT expected, production FROM metric_coverage WHERE ticker=? AND evidence=?",
                (ticker, encoded(versions.get(ticker, []))),
            ).fetchone()
        old_native, old_public = map(json.loads, saved) if saved else ({}, {})
        for form, scope in (
            ("NSBU", "separate"),
            ("MSFO", "separate"),
            ("MSFO", "consolidated"),
        ):
            for freq in ("annual", "quarter", "interim"):
                view = f"statement:{form}:{scope}:{freq}"
                args = (ticker, form, scope, freq)
                prior = (
                    (old_native[view], old_public[view])
                    if view in old_native and view in old_public
                    else None
                )
                if ticker in expected and ticker in actual:
                    left, right = verify_statement(
                        partial(read, local, *args), partial(read, public, *args), prior
                    )
                    expected[ticker][view], actual[ticker][view] = left, right
                elif ticker in expected:
                    expected[ticker][view] = read(local, *args)
                else:
                    actual[ticker][view] = read(public, *args)


def evidence(companies):
    import dbx
    from catalogue.storage import get_catalog_conn
    from financial_columns import share_disclosures

    orgs = defaultdict(list)
    for c in companies:
        orgs[str(c.get("org_id"))].append(c["ticker"])
    versions = defaultdict(list)
    queries = {
        "financial_form_heads": "SELECT issuer_id, standard, scope, period_end, version_id FROM financial_form_heads",
        "ingest_heads": "SELECT org_id,standard,scope,period_end,snapshot_id FROM ingest_heads",
        "ingest_sources": "SELECT org_id,category,url,latest_version FROM ingest_sources WHERE latest_version IS NOT NULL",
        "share_disclosure_heads": "SELECT issuer_id,ticker,scope,period_end,version_id FROM share_disclosure_heads",
    }
    with closing(get_catalog_conn()) as conn:
        tables = set(dbx.tables(conn))
        aliases = {
            t: c["ticker"]
            for c in companies
            for t in (c.get("tickers") or [c["ticker"]])
        }
        if "catalog_reports" in tables:
            for row in conn.execute(
                "SELECT ticker,report_form,year,quarter,published_at,excel_url,excel_url_form1,pdf_url FROM catalog_reports"
            ):
                record = dict(row)
                t = aliases.get(record.pop("ticker"))
                if t:
                    versions[t].append(["catalog_report", record])

        if "catalog_structured_quarters" in tables:
            for row in conn.execute("SELECT ticker,year,quarter,source_json FROM catalog_structured_quarters"):
                version = json.loads(row["source_json"]).get("statement_version")
                ticker = aliases.get(row["ticker"])
                if version and ticker:
                    versions[ticker].append(["microfinance_quarter", row["year"], row["quarter"], version])

        for table, query in queries.items():
            if table in tables:
                for row in conn.execute(query):
                    values = list(dict(row).values())
                    for t in orgs[str(values[0])]:
                        versions[t].append([table, *values[1:]])
    for (org, t, end, scope), (disclosure, version) in share_disclosures._reviewed(
        share_disclosures.REVIEWED
    ).items():
        if org in orgs:
            for symbol in orgs[org]:
                versions[symbol].append(
                    ["reviewed_share", t, scope, end, version, disclosure["source_url"]]
                )
    return {t: sorted(rows, key=encoded) for t, rows in versions.items()}


def discrepancies(expected, live):
    issues = {}
    for view in expected.keys() | live.keys():
        left, right = expected.get(view, {}), live.get(view, {})
        for key in left.keys() | right.keys():
            a, b = left.get(key), right.get(key)
            if a != b:
                issues[f"{view}/{key}"] = {"expected": a, "production": b}
            elif b and (
                b["status"] in {"earlier", "gap", "other_filing"}
                or b.get("filing_issues")
            ):
                issues[f"{view}/{key}"] = {"production": b}
    return issues


def save(db, versions, expected, live):
    changes, alerts = 0, []
    with db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS metric_coverage (ticker TEXT PRIMARY KEY, evidence TEXT, expected TEXT, production TEXT, discrepancies TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS metric_coverage_events (id INTEGER PRIMARY KEY, ticker TEXT, metric TEXT, previous TEXT, current TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        prior = {r[0]: r[1:] for r in db.execute("SELECT * FROM metric_coverage")}
        for ticker in sorted(expected.keys() | live.keys() | prior.keys()):
            old = prior.get(ticker)
            a, b = expected.get(ticker, {}), live.get(ticker, {})
            issues = discrepancies(a, b)
            fields = tuple(map(encoded, (versions.get(ticker, []), a, b, issues)))
            if old == fields:
                continue
            if ticker not in expected and ticker not in live:
                db.execute("DELETE FROM metric_coverage WHERE ticker=?", (ticker,))
            else:
                db.execute(
                    "INSERT INTO metric_coverage VALUES(?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET evidence=excluded.evidence, expected=excluded.expected, production=excluded.production, discrepancies=excluded.discrepancies",
                    (ticker, *fields),
                )
            changes += 1
            previous = json.loads(old[-1]) if old else {}
            for metric in sorted(previous.keys() | issues.keys()):
                before, after = previous.get(metric), issues.get(metric)
                if before != after:
                    db.execute(
                        "INSERT INTO metric_coverage_events(ticker,metric,previous,current) VALUES(?,?,?,?)",
                        (ticker, metric, encoded(before), encoded(after)),
                    )
                    alerts.append(
                        {"ticker": ticker, "metric": metric, "discrepancy": after}
                    )
    return {"changes": changes, "alerts": alerts}


def public_get(session, path, params, *, sleep=time.sleep):
    url = "https://uzstock.uz" + (
        path if path.startswith("/") else "/api/terminal/" + path
    )
    for attempt in range(4):
        delay = 2**attempt
        try:
            response = session.get(url, params=params, timeout=(12, 150))
            if response.status_code in (408, 429, 500, 502, 503, 504):
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    delay = max(delay, Retry().parse_retry_after(retry_after))
                if attempt < 3:
                    sleep(delay)
                    continue
            response.raise_for_status()
            return response.json()
        except (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.JSONDecodeError,
        ):
            if attempt == 3:
                raise
            sleep(delay)


def run():
    from db import APP_DATA_DIR
    from securities_catalog import get_securities_map
    from server.terminal import service

    folder = Path(APP_DATA_DIR)
    with (
        (folder / "metric-coverage.lock").open("a") as lock,
        requests.Session() as session,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX)

        def public(path, **params):
            return public_get(session, path, params)

        def local(path, **params):
            if path.startswith("/api/company/"):
                from financial_columns.service import load

                return load(path.split("/")[3], **params)
            if path == "screener":
                return asyncio.run(service.screener(**params))
            return service.filing_metrics(period=None, search="", **params)

        companies = service.universe(all_filings=True)
        securities = get_securities_map()
        types = {
            c["ticker"]: {
                "kind": c["kind"],
                "security": securities.get(c["ticker"]),
            }
            for c in companies
        }
        versions = evidence(companies)
        log.info("Recomputing metric coverage from %d issuer records", len(companies))
        expected = snapshot(local, types)
        if set(expected) != set(types) or not types:
            raise ValueError("incomplete local issuer universe")
        log.info("Verifying recalculated metrics through uzstock.uz")
        actual = snapshot(public, types)
        with closing(
            sqlite3.connect(folder / "metric-coverage.sqlite3", timeout=30)
        ) as db:
            check_statements(db, expected, actual, versions, local, public)
            report = save(db, versions, expected, actual)
        for alert in report["alerts"]:
            log.warning(
                "Metric coverage %s %s %s",
                alert["ticker"],
                alert["metric"],
                "changed" if alert["discrepancy"] else "resolved",
            )
        log.info(
            "Metric coverage checked %d issuers, %d changed, %d changed discrepancies",
            len(expected),
            report["changes"],
            len(report["alerts"]),
        )
        return {
            "issuers": len(expected),
            "changes": report["changes"],
            "alerts": len(report["alerts"]),
        }
