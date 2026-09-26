"""Financials backfill operations with explicit dependencies."""
from __future__ import annotations
import reports_catalog as rc
import catalogue.facts as catalogue_facts
import catalogue.fields as catalogue_fields
import catalogue.history as catalogue_history
import catalogue.sources as catalogue_sources
import catalogue.storage as catalogue_storage
import catalogue.sync as catalogue_sync

import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.settings as collectors_financials_settings
import os

import catalogue.fields as catalogue_fields
import catalogue.filings as catalogue_filings
import catalogue.financial_store as catalogue_financial_store
import catalogue.history as catalogue_history
import catalogue.parsing as catalogue_parsing
import catalogue.refresh as catalogue_refresh
import catalogue.sources as catalogue_sources
import requests
import time


def backfill_financials(min_year: int = 2015, tickers: set[str] | None = None) -> int:
    """Parse every issuer's historical ANNUAL filing into the financials cache.

    The pipeline only ever parsed the LATEST annual report per ticker — 94 rows
    across 68 issuers — because that is all the market board needs. So the
    company page had no multi-year income statement to draw, and the fact store
    it fell back to carries no gross profit or operating income at all: only
    margins, and those on a basis we could not verify.

    The filings are the authority and they parse cleanly at any age. UZTL's
    2022, 2023, 2024 and 2025 annuals all yield revenue, gross profit, operating
    income and net profit, and they agree with the fact store exactly where the
    store is right (2025, 2022, 2020) — which is how the store was caught with
    UZTL's 2023 and 2024 revenue TRANSPOSED and 2021 missing entirely.

    One parse fills both caches: the six sums into catalog_financials and the
    ratios computed from the same two statements into catalog_ratios, so every
    year on the page comes from one filing rather than from two sources that
    disagree.
    """
    from securities_catalog import get_securities_map

    requested_tickers = {str(t).strip().upper() for t in (tickers or set()) if str(t).strip()}
    tickers = requested_tickers or {str(t).upper() for t in (get_securities_map() or {})}
    # The deployment's board is the universe the site serves, and it is wider
    # than this machine's catalog (109 vs 78, measured 2026-08-10) — the same
    # trap the quote-history backfill hit. Sourced locally, every board-only
    # issuer (JASM, TGPG, SANE, ORGS, KFSK ...) kept a single parsed year while
    # nine to eleven annuals sat in the report catalog unread.
    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    for kind in ("stock", "bond"):
        if requested_tickers:
            break
        try:
            resp = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60)
            resp.raise_for_status()
            board = resp.json()
            board = board if isinstance(board, list) else board.get("stocks") or []
            tickers |= {str(r.get("ticker") or "").strip().upper()
                        for r in board if r.get("ticker")}
        except Exception:  # noqa: BLE001 — the local catalog still gives us a run
            collectors_financials_settings.log.exception("financials backfill: could not read the deployment's %s board", kind)
    tickers = sorted(t for t in tickers if t)
    collectors_financials_settings.log.info("financials backfill: %d tickers, annual reports from %d", len(tickers), min_year)
    rows: list[dict] = []
    ratio_rows: list[dict] = []
    ratios_written = 0
    scanned = failed = 0
    for index, ticker in enumerate(tickers, 1):
        try:
            reports = catalogue_filings.get_company_reports(ticker) or []
        except Exception:
            collectors_financials_settings.log.exception("financials backfill: cannot list reports for %s", ticker)
            failed += 1
            continue
        years = sorted({int(r["year"]) for r in reports
                        if r.get("report_form") == "NSBU" and not r.get("quarter")
                        and str(r.get("year") or "").isdigit() and int(r["year"]) >= min_year},
                       reverse=True)
        for year in years:
            scanned += 1
            try:
                data = catalogue_sources.fetch_report_excel_data(ticker, "NSBU", year, 0, use_snapshot_cache=False)
                if not data.get("ok"):
                    failed += 1
                    collectors_financials_settings.log.warning("annual backfill: %s %s: %s", ticker, year, data.get("error"))
                    continue
                ratios = catalogue_parsing.compute_financial_ratios(data.get("income"), data.get("balance")) or {}
                vals = ratios.get("source_values") or {}
                if not any(vals.get(k) is not None for k in catalogue_fields.FIN_MONEY_FIELDS):
                    failed += 1
                    continue
                rows.append({"ticker": ticker, "year": year, "quarter": 0,
                             **{k: vals.get(k) for k in catalogue_fields.FIN_MONEY_FIELDS}})
                # ТЗ Дополнение 1 §Б.2: the filing this parse consumed is
                # registered and the figures recorded against it, exactly as the
                # latest-annual pass does. Writing the rows WITHOUT this left
                # 450 figures in the cache with no source — the provenance
                # backfill then linked them to reports it had never parsed, and
                # test_the_backfill_links_figures_cached_before_provenance_existed
                # caught it.
                report_id = catalogue_refresh._register_parse(ticker, "NSBU", year, 0, data, vals)
                # The collector's own cache mirrors what it pushes, so a later
                # run reads the same history the deployment is serving.
                catalogue_financial_store.upsert_financials_cache(ticker, "NSBU", year, 0, vals, report_id)
                metrics = ratios.get("metrics") or {}
                if any(v is not None for v in metrics.values()):
                    catalogue_financial_store.upsert_ratio_cache(ticker, "NSBU", year, 0, metrics)
                    ratio_rows.append({"ticker": ticker, "year": year, "quarter": 0, **metrics})
                    ratios_written += 1
            except Exception:
                collectors_financials_settings.log.exception("financials backfill: %s %s failed", ticker, year)
                failed += 1
            time.sleep(0.2)
        if index % 10 == 0:
            collectors_financials_settings.log.info("financials backfill: %d/%d tickers, %d periods parsed",
                     index, len(tickers), len(rows))
    collectors_financials_settings.log.info("financials backfill: %d periods from %d reports (%d failures), %d ratio rows",
             len(rows), scanned, failed, ratios_written)
    if not rows:
        return 1
    status = 1 if failed else 0
    # upsert, never replace: the newest period the board reads must survive a
    # backfill that is only adding history behind it.
    for start in range(0, len(rows), 500):
        status = collectors_financials_delivery._post("/api/admin/financials",
                       {"form": "NSBU", "mode": "upsert",
                        "rows": rows[start:start + 500],
                        "ratios": ratio_rows[start:start + 500]}) or status
    return status


def backfill_quarterly_financials(min_year: int = 2023,
                                  tickers: set[str] | None = None) -> int:
    """Parse every issuer's QUARTERLY filing into the financials cache.

    The daily pipeline keeps only the newest cumulative quarter per ticker —
    all the market board's multiples need — so when the company page grew a
    quarterly view there were 24 quarterly rows behind it against ~650 quarterly
    reports the catalog already knew about (66 issuers, Q1–Q3 each year; the
    annual stands in for Q4). Same shape as :func:`backfill_financials`: one
    parse fills catalog_financials, registers provenance, and the batch is
    PUSHED as an upsert so history lands behind whatever the board is serving.

    Quarterly form 2 is cumulative from 1 January — stored as filed. The API
    differences the running totals into three-month columns at read time, so
    this stays a faithful copy of the source.
    """
    from securities_catalog import get_securities_map

    requested_tickers = {str(t).strip().upper() for t in (tickers or set()) if str(t).strip()}
    tickers = requested_tickers or {str(t).upper() for t in (get_securities_map() or {})}
    # The deployment's board is the universe the site serves — wider than this
    # machine's catalog. Same trap, same fix as the annual backfill above.
    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    for kind in ("stock", "bond"):
        if requested_tickers:
            break
        try:
            resp = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60)
            resp.raise_for_status()
            board = resp.json()
            board = board if isinstance(board, list) else board.get("stocks") or []
            tickers |= {str(r.get("ticker") or "").strip().upper()
                        for r in board if r.get("ticker")}
        except Exception:  # noqa: BLE001 — the local catalog still gives us a run
            collectors_financials_settings.log.exception("quarterly backfill: could not read the deployment's %s board", kind)
    tickers = sorted(t for t in tickers if t)
    collectors_financials_settings.log.info("quarterly backfill: %d tickers, quarterly reports from %d", len(tickers), min_year)
    rows: list[dict] = []
    scanned = failed = 0
    for index, ticker in enumerate(tickers, 1):
        try:
            reports = catalogue_filings.get_company_reports(ticker) or []
        except Exception:
            collectors_financials_settings.log.exception("quarterly backfill: cannot list reports for %s", ticker)
            failed += 1
            continue
        quarters = sorted({(int(r["year"]), int(r["quarter"])) for r in reports
                           if r.get("report_form") == "NSBU" and r.get("quarter")
                           and str(r.get("year") or "").isdigit() and int(r["year"]) >= min_year},
                          reverse=True)
        for year, quarter in quarters:
            scanned += 1
            try:
                data = catalogue_sources.fetch_report_excel_data(ticker, "NSBU", year, quarter, use_snapshot_cache=False)
                if not data.get("ok"):
                    failed += 1
                    collectors_financials_settings.log.warning("quarterly backfill: %s %sQ%s: %s", ticker, year, quarter, data.get("error"))
                    continue
                ratios = catalogue_parsing.compute_financial_ratios(data.get("income"), data.get("balance")) or {}
                vals = ratios.get("source_values") or {}
                if not any(vals.get(k) is not None for k in catalogue_fields.FIN_MONEY_FIELDS):
                    failed += 1
                    continue
                rows.append({"ticker": ticker, "year": year, "quarter": quarter,
                             **{k: vals.get(k) for k in catalogue_fields.FIN_MONEY_FIELDS}})
                # Provenance first, mirror second — the same order the annual
                # backfill settled on, for the same reasons.
                report_id = catalogue_refresh._register_parse(ticker, "NSBU", year, quarter, data, vals)
                catalogue_financial_store.upsert_financials_cache(ticker, "NSBU", year, quarter, vals, report_id)
            except Exception:
                collectors_financials_settings.log.exception("quarterly backfill: %s %sQ%s failed", ticker, year, quarter)
                failed += 1
            time.sleep(0.2)
        if index % 10 == 0:
            collectors_financials_settings.log.info("quarterly backfill: %d/%d tickers, %d periods parsed",
                     index, len(tickers), len(rows))
    collectors_financials_settings.log.info("quarterly backfill: %d periods from %d reports (%d failures)",
             len(rows), scanned, failed)
    if not rows:
        return 1
    status = 1 if failed else 0
    # upsert, never replace: the newest cumulative quarter the board reads must
    # survive a backfill that is only adding history behind it.
    for start in range(0, len(rows), 500):
        status = collectors_financials_delivery._post("/api/admin/financials",
                       {"form": "NSBU", "mode": "upsert",
                        "rows": rows[start:start + 500]}) or status
    return status


def backfill_current_section(periods_per_ticker: int = 2) -> int:
    """Re-parse the newest filings so the balance's CURRENT section is stored.

    The liquidity, quick and asset-turnover coefficients are computed from
    current assets, stocks and current liabilities — three lines every issuer
    files and this platform did not keep, which is why the board's
    «Коэффициенты» columns were blank for the 39 issuers whose indicator feed
    publishes none of them. The columns exist now; this fills them from the
    filings already catalogued, newest first, and pushes the full parsed row (a
    partial push would blank the headline sums beside it).
    """
    from securities_catalog import get_securities_map

    tickers = {str(t).upper() for t in (get_securities_map() or {})}
    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    for kind in ("stock", "bond"):
        try:
            resp = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60)
            resp.raise_for_status()
            board = resp.json()
            board = board if isinstance(board, list) else board.get("stocks") or []
            tickers |= {str(r.get("ticker") or "").strip().upper()
                        for r in board if r.get("ticker")}
        except Exception:  # noqa: BLE001 — the local catalog still gives us a run
            collectors_financials_settings.log.exception("current-section backfill: cannot read the deployment's %s board", kind)
    tickers = sorted(t for t in tickers if t)
    collectors_financials_settings.log.info("current-section backfill: %d tickers, %d annual + %d quarterly each",
             len(tickers), periods_per_ticker, periods_per_ticker)
    rows: list[dict] = []
    filled = failed = 0
    for index, ticker in enumerate(tickers, 1):
        try:
            reports = catalogue_filings.get_company_reports(ticker) or []
        except Exception:
            collectors_financials_settings.log.exception("current-section backfill: cannot list reports for %s", ticker)
            failed += 1
            continue
        nsbu = [r for r in reports if r.get("report_form") == "NSBU"
                and str(r.get("year") or "").isdigit()]
        annuals = sorted({int(r["year"]) for r in nsbu if not r.get("quarter")}, reverse=True)
        quarters = sorted({(int(r["year"]), int(r["quarter"])) for r in nsbu if r.get("quarter")},
                          reverse=True)
        periods = ([(y, 0) for y in annuals[:periods_per_ticker]]
                   + list(quarters[:periods_per_ticker]))
        for year, quarter in periods:
            try:
                values = catalogue_history.parse_catalogued_report(ticker, "NSBU", year, quarter)
            except Exception:
                collectors_financials_settings.log.exception("current-section backfill: %s %sQ%s failed", ticker, year, quarter)
                failed += 1
                continue
            if not any(values.get(k) is not None for k in catalogue_fields.FIN_MONEY_FIELDS):
                continue
            if values.get("current_assets") is not None:
                filled += 1
            rows.append({"ticker": ticker, "year": year, "quarter": quarter,
                         **{k: values.get(k) for k in catalogue_fields.FIN_MONEY_FIELDS}})
            report_id = catalogue_refresh._register_parse(ticker, "NSBU", year, quarter,
                                           {"ok": True}, values)
            catalogue_financial_store.upsert_financials_cache(ticker, "NSBU", year, quarter, values, report_id)
            time.sleep(0.2)
        if index % 10 == 0:
            collectors_financials_settings.log.info("current-section backfill: %d/%d tickers, %d rows (%d with a current section)",
                     index, len(tickers), len(rows), filled)
    collectors_financials_settings.log.info("current-section backfill: %d rows, %d carry a current section (%d failures)",
             len(rows), filled, failed)
    if not rows:
        return 1
    status = 0
    for start in range(0, len(rows), 500):
        status = collectors_financials_delivery._post("/api/admin/financials",
                       {"form": "NSBU", "mode": "upsert",
                        "rows": rows[start:start + 500]}) or status
    return status


def backfill_quarter_history(limit_per_ticker: int = 40) -> int:
    """Reach BEHIND the source's ten-quarter window and bank what it forgot.

    openinfo's structured quarterly endpoint answers with the ten most recent
    filings for an issuer and refuses every paging parameter, so
    :func:`backfill_quarterly_financials` — which works off the report catalogue
    the structured sync builds — can never see a quarter that closed before the
    window opened. Measured 2026-08-17: org 446 has published thirty quarterlies
    since 2016 and the catalogue knew ten of them.

    The unified feed lists all thirty. ``harvest_historical_quarters`` fetches
    each workbook this catalogue has never recorded, reads the period out of the
    filing itself, and lands both the document and its figures; this walks the
    board with it and pushes the batch the way the other backfills do.
    """
    from securities_catalog import get_securities_map

    tickers = {str(t).upper() for t in (get_securities_map() or {})}
    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    for kind in ("stock", "bond"):
        try:
            resp = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60)
            resp.raise_for_status()
            board = resp.json()
            board = board if isinstance(board, list) else board.get("stocks") or []
            tickers |= {str(r.get("ticker") or "").strip().upper()
                        for r in board if r.get("ticker")}
        except Exception:  # noqa: BLE001 — the local catalog still gives us a run
            collectors_financials_settings.log.exception("quarter-history backfill: cannot read the deployment's %s board", kind)
    tickers = sorted(t for t in tickers if t)
    collectors_financials_settings.log.info("quarter-history backfill: %d tickers, up to %d filings each",
             len(tickers), limit_per_ticker)
    rows: list[dict] = []
    failed = 0
    for index, ticker in enumerate(tickers, 1):
        try:
            result = catalogue_history.harvest_historical_quarters(ticker, limit=limit_per_ticker)
        except Exception:
            collectors_financials_settings.log.exception("quarter-history backfill: %s failed", ticker)
            failed += 1
            continue
        rows.extend(result["rows"])
        if result["errors"]:
            # Not a failure of the sweep: a 2016 filing with an unreadable
            # workbook is a fact about the source, and naming it is how the next
            # run knows the gap is not ours.
            collectors_financials_settings.log.info("quarter-history backfill: %s — %s", ticker,
                     "; ".join(result["errors"][:4]))
        if result["added"]:
            collectors_financials_settings.log.info("quarter-history backfill: %s +%d periods", ticker, result["added"])
        if index % 10 == 0:
            collectors_financials_settings.log.info("quarter-history backfill: %d/%d tickers, %d periods",
                     index, len(tickers), len(rows))
    collectors_financials_settings.log.info("quarter-history backfill: %d new periods (%d ticker failures)", len(rows), failed)
    if not rows:
        return 0 if not failed else 1
    status = 0
    for start in range(0, len(rows), 500):
        status = collectors_financials_delivery._post("/api/admin/financials",
                       {"form": "NSBU", "mode": "upsert",
                        "rows": rows[start:start + 500]}) or status
    return status


def backfill_company_quarter_history(ticker: str, limit: int = 40) -> int:

    """Publish the pre-window quarterly filings for one issuer.



    This is deliberately separate from :func:`backfill_quarter_history`: the

    latter walks the whole market and is suitable for a planned maintenance

    pass, whereas a missing company page must be repairable immediately.  The

    unified OpenInfo feed holds the old filing ids and URLs, but a normal daily

    sync sees only the source's ten newest quarters.  Harvesting one issuer

    both catalogues those documents and pushes their extracted figures to the

    production API.

    """

    requested = str(ticker or "").strip().upper()

    if not requested or not requested.isalnum():

        raise ValueError("ticker must contain letters and numbers only")

    result = catalogue_history.harvest_historical_quarters(requested, limit=max(1, limit))

    errors = result.get("errors") or []

    if errors:

        collectors_financials_settings.log.warning("quarter-history backfill for %s: %s", requested, "; ".join(errors[:4]))

    rows = result.get("rows") or []

    if not rows:

        # Idempotency matters: a rerun after a successful repair should not be

        # reported as a failed production action merely because every filing is

        # already catalogued.

        return 1 if errors else 0

    status = 1 if errors else 0

    for start in range(0, len(rows), 500):

        status = collectors_financials_delivery._post("/api/admin/financials", {

            "form": "NSBU",

            "mode": "upsert",

            "rows": rows[start:start + 500],

        }) or status

    return status


def _bank_history_remote_attempt(ticker: str) -> str:
    """Rotation lives on the API; production collector containers are ephemeral."""
    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    response = requests.get(f"{base}/api/facts/{ticker}", params={"dataset": "bank_history"}, timeout=20)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError("Bank history checkpoint read failed")
    rows = body.get("datasets", {}).get("bank_history", {}).get("last_attempt", [])
    return max((str(row.get("value") or "") for row in rows if row.get("source") == "collector"), default="")


def backfill_bank_financials(limit: int = 2, *, force: bool = False,
                            ticker: str | None = None) -> int:
    """Repair a rotating batch of bank issuers, including already catalogued gaps.

    Discover old quarters first, then re-parse ALL catalogued annuals and quarters.
    This also retries a previous failed push: catalogue presence is not proof that
    the API received the figures. The attempted-at marker rotates failed issuers
    too, so one malformed filing cannot starve every other bank.
    """
    from datetime import datetime, timedelta, timezone

    if limit <= 0:
        return 0
    conn = catalogue_storage.get_catalog_conn()
    try:
        candidates = conn.execute("""
            SELECT DISTINCT c.ticker, c.company_name, c.org_id
            FROM catalog_companies c JOIN catalog_reports r ON r.ticker=c.ticker
            WHERE c.org_id IS NOT NULL AND r.report_form='NSBU'
              AND (r.excel_url LIKE '%org_type=bank%' OR r.excel_url_form1 LIKE '%org_type=bank%')
            ORDER BY c.ticker
        """).fetchall()
    finally:
        conn.close()
    # Ordinary/preferred shares and bank bonds share one financial statement.
    issuers = {}
    for row in sorted(candidates, key=lambda r: (str(r["ticker"]).endswith("P"), len(r["ticker"]), r["ticker"])):
        issuers.setdefault(str(row["org_id"]), dict(row))
    if ticker:
        requested = str(ticker).strip().upper()
        selected_orgs = {str(row["org_id"]) for row in candidates if row["ticker"] == requested}
        issuers = {org: row for org, row in issuers.items() if org in selected_orgs}
    if force and not issuers:
        collectors_financials_settings.log.error("No matching bank issuer is catalogued; sync the report catalog first")
        return 1
    attempts = {str(f["entity_id"]): str(f.get("value_text") or "")
                for f in catalogue_facts.get_facts(dataset="bank_history") if f["field"] == "last_attempt"}
    if not force:
        for org, company in issuers.items():
            attempts[org] = max(attempts.get(org, ""), _bank_history_remote_attempt(company["ticker"]))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    due = sorted((row for org, row in issuers.items()
                  if force or attempts.get(org, "") < cutoff),
                 key=lambda row: (attempts.get(str(row["org_id"]), ""), row["ticker"]))
    status = 0
    for company in due[:limit]:
        ticker, org_id = company["ticker"], str(company["org_id"])
        result = 0
        try:
            sync = catalogue_sync.sync_company(ticker, company["company_name"], force=True, org_id=org_id)
            if sync.get("errors"):
                raise RuntimeError("; ".join(sync["errors"]))
            links = catalogue_history.repair_statement_links(ticker)
            collectors_financials_settings.log.info("bank history %s: recovered %d document links (%d unresolved)",
                     ticker, len(links["repaired"]), len(links["unresolved"]))
            # Harvest alone skips known ids. The two parses below are required
            # even on a rerun, including when its first upload failed.
            result = backfill_company_quarter_history(ticker, limit=200) or result
            result = backfill_financials(2015, tickers={ticker}) or result
            result = backfill_quarterly_financials(2015, tickers={ticker}) or result
            # Discovery is not publication. A separate restart-safe PDF worker
            # stages candidates; only explicit approval/publication changes MSFO.
            from financial_ingestion import documents, extract, store
            discovered = documents.discover(ticker=ticker, processor=extract.processor_version())
            ifrs = store.status(org_id)
            collectors_financials_settings.log.info("bank IFRS %s: discovered=%d coverage=%s pending=%d unreviewed=%d",
                     ticker, discovered["sources"], ifrs["status"], ifrs["pending_jobs"], ifrs["unreviewed_sources"])
            catalogue_facts.upsert_facts([{"entity_id": org_id, "dataset": "ifrs_history", "field": "status",
                              "value": ifrs["status"], "source": "financial_ingestion"}])
        except Exception:
            collectors_financials_settings.log.exception("bank history repair failed for %s", ticker)
            result = 1
        marker = [
            {"entity_id": org_id, "dataset": "bank_history", "field": "last_attempt",
             "value": datetime.now(timezone.utc).isoformat(), "source": "collector"},
            {"entity_id": org_id, "dataset": "bank_history", "field": "status",
             "value": "partial" if result else "ok", "source": "collector"},
        ]
        # Push failures are reported, and the local rotation survives both API
        # outages and collector restarts on the server's shared data volume.
        result = collectors_financials_delivery._post("/api/admin/facts", {"rows": marker}) or result
        if result:
            marker[1]["value"] = "partial"
        catalogue_facts.upsert_facts(marker)
        status = result or status
    collectors_financials_settings.log.info("bank history: %d issuers due, %d attempted, status=%d", len(due), min(limit, len(due)), status)
    if due:
        collectors_financials_delivery._stamp_step("bank_history", "partial" if status else "ok")
    return status
