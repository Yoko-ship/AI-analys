"""Refresh financial snapshots from their catalogued source documents."""
from __future__ import annotations
import catalogue.filings as catalogue_filings
from typing import Any
import sqlite3

from entity_resolver import ORG_OVERRIDES
import catalogue.fields as catalogue_fields
import catalogue.financial_store as catalogue_financial_store
import catalogue.parsing as catalogue_parsing
import catalogue.periods as catalogue_periods
import catalogue.settings as catalogue_settings
import catalogue.sources as catalogue_sources
import catalogue.storage as catalogue_storage
import catalogue.sync as catalogue_sync


def _fin_candidates(conn: sqlite3.Connection, form: str, ttl_days: int,
                    tickers: list[str] | None) -> list[dict[str, Any]]:
    """Best parseable report per ticker lacking a fresh cache.

    Considers only reports that have an Excel export (PDF-only issuers can't be
    parsed). Selection rules, in order:

      * a premature annual (fiscal year not yet ended — openinfo's current-year
        placeholder) is never a candidate;
      * a recent annual for the most recent *completed* fiscal year wins outright —
        it is the honest full-year figure, preferred over any fresher partial quarter;
      * once that annual has aged beyond ``FINANCIALS_ANNUAL_FRESH_DAYS``, a newer
        quarterly filing wins, rather than leaving the analysis a year behind;
      * otherwise the freshest report wins (a newer quarter beats an older annual),
        so an issuer whose latest completed annual is missing (it filed only IFRS
        that year, or files only quarterly like GRBK) still shows current figures
        instead of a year-plus-stale annual.

    Returns ``[{ticker, year, quarter}]``, newest first.
    """
    ticker_filter = ""
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        ticker_filter = f"AND r.ticker IN ({placeholders})"
    # Bind order follows the placeholders top-to-bottom: the TTL cutoff in the
    # JOIN's datetime(), then report_form, then any ticker filter.
    params = [f"-{ttl_days} days", form, *(tickers or [])]
    rows = conn.execute(
        f"""
        SELECT r.ticker, r.period_type, r.year, r.quarter
        FROM catalog_reports r
        LEFT JOIN catalog_financials f
          ON f.ticker = r.ticker AND f.form = r.report_form
         AND f.year = r.year AND f.quarter = COALESCE(r.quarter, 0)
         AND f.updated_at >= datetime('now', ?)
        WHERE r.report_form = ? AND r.excel_url IS NOT NULL
          AND r.year IS NOT NULL {ticker_filter}
          AND f.ticker IS NULL
        """,
        params,
    ).fetchall()
    last_fy = catalogue_periods._latest_complete_fiscal_year()
    best: dict[str, tuple] = {}
    for r in rows:
        t = r["ticker"]
        year = r["year"]
        quarter = r["quarter"] or 0
        is_annual = r["period_type"] == "annual"
        if is_annual and year is not None and year > last_fy:
            continue  # premature placeholder annual — never a candidate
        if is_annual and year == last_fy and catalogue_periods._completed_annual_is_recent(year):
            key = (2, year, 1, 0)  # recent completed annual: outranks partial quarters
        else:
            key = (1, year or 0, 1 if is_annual else 0, quarter)  # else freshest wins
        if t not in best or key > best[t][0]:
            best[t] = (key, {"ticker": t, "year": year, "quarter": quarter})
    return [
        v[1] for v in sorted(
            best.values(),
            key=lambda x: (x[1]["year"] or 0, x[1]["quarter"]),
            reverse=True,
        )
    ]


def _sync_missing_companies(form: str, sync_limit: int) -> int:
    """Sync a bounded batch of companies that have no catalog reports yet.

    Lets a fresh backend bootstrap its catalog (and therefore financials)
    progressively over successive market loads, so the columns fill in without a
    manual ``sync_all``. Returns the number of companies synced this call.
    """
    if sync_limit <= 0:
        return 0
    conn = catalogue_storage.get_catalog_conn()
    have = {r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM catalog_reports").fetchall()}
    conn.close()
    pending = [
        t for t in catalogue_settings._TICKER_TO_NAME
        if t not in have and not (t.endswith("P") and t[:-1] in catalogue_settings._TICKER_TO_NAME)
    ]
    synced = 0
    for ticker in pending[:sync_limit]:
        try:
            catalogue_sync.sync_company(ticker, catalogue_settings._TICKER_TO_NAME.get(ticker, ticker))
            synced += 1
        except Exception:
            catalogue_settings.logger.exception("warmup catalog sync failed for %s", ticker)
    return synced


def _latest_excel_report(ticker: str, form: str,
                         exclude: tuple[int, int] | None = None) -> dict[str, int] | None:
    """Newest report (any period type) with an Excel export, for a fallback.

    ``_fin_candidates`` prefers the latest *annual* report, but some issuers only
    have an old annual (sometimes an empty filing) plus recent quarterly data
    (e.g. KSCM: newest annual is 2021, but 2026 Q1 has real figures). When the
    preferred report yields nothing, we retry with the most recent report that
    exists so those companies still populate.
    """
    conn = catalogue_storage.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT year, quarter FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND excel_url IS NOT NULL AND year IS NOT NULL
        ORDER BY year DESC, quarter DESC
        """,
        (ticker, form),
    ).fetchall()
    conn.close()
    for r in rows:
        yq = (r["year"], r["quarter"] or 0)
        if exclude and yq == exclude:
            continue
        if yq[1] == 0 and catalogue_periods._is_premature_annual_year(yq[0]):
            continue  # skip the current-year placeholder annual
        return {"year": yq[0], "quarter": yq[1]}
    return None


def refresh_financials_from_pdf(tickers: list[str] | None = None, limit: int = 80) -> dict[str, Any]:
    """Fill financials from the NSBU report PDF for issuers whose Excel export is
    broken on openinfo (microfinance MCHJ and similar).

    Targets tickers that have an NSBU pdf_url but no cached financials, parsing the
    latest report (annual preferred). This is the last-resort source after the
    structured accounting-report and Excel paths.
    """
    from collectors.openinfo.documents import fetch_report_documents
    from collectors.openinfo.pdf import parse_nsbu_pdf_financials

    conn = catalogue_storage.get_catalog_conn()
    ticker_filter = ""
    params: list[Any] = []
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        ticker_filter = f"AND r.ticker IN ({placeholders})"
        params = list(tickers)
    rows = conn.execute(
        f"""
        SELECT r.ticker, c.company_name, c.org_id, r.period_type, r.year, r.quarter
        FROM catalog_reports r
        JOIN catalog_companies c ON c.ticker = r.ticker
        LEFT JOIN catalog_financials f ON f.ticker = r.ticker AND f.form = 'NSBU'
        WHERE r.report_form = 'NSBU' AND r.year IS NOT NULL AND f.ticker IS NULL {ticker_filter}
        """,
        params,
    ).fetchall()
    conn.close()

    best: dict[str, tuple] = {}  # newest report per ticker (annual beats quarter)
    for r in rows:
        rank = (1 if r["period_type"] == "annual" else 0, r["year"], r["quarter"] or 0)
        if r["ticker"] not in best or rank > best[r["ticker"]][0]:
            best[r["ticker"]] = (rank, r)

    session = catalogue_sources._make_session()
    updated = 0
    updated_tickers: list[str] = []
    unresolved: list[str] = []
    errors: list[dict] = []
    for ticker, (_, r) in list(best.items())[:limit]:
        # This is the last-resort source and it writes straight into the served
        # financials, so it must be the STRICTEST about identity, not the loosest.
        # Searching by company name with no org filter meant a name that shares
        # words with a larger issuer returned that issuer's PDF, and its balance
        # sheet was then stored as this ticker's — the KVTS/BIOK failure mode.
        org_id = ORG_OVERRIDES.get(ticker) or (str(r["org_id"]).strip() if r["org_id"] else "")
        if not org_id:
            unresolved.append(ticker)
            continue
        try:
            # The stored pdf_url can carry a wrong report id for microfinance, so
            # fetch the live report list to get the current, correct PDF link.
            docs = fetch_report_documents(r["company_name"] or ticker, org_id=org_id,
                                          session=session)
            nsbu = [d for d in docs["items"]
                    if d.get("report_form") == "NSBU" and d.get("pdf_url")
                    and str(d.get("organization_id")) == str(org_id)]
            if not nsbu:
                continue
            nsbu.sort(key=lambda d: (d.get("period_type") == "annual", str(d.get("published_at") or "")), reverse=True)
            fin = parse_nsbu_pdf_financials(session, nsbu[0]["pdf_url"])
        except Exception as exc:  # noqa: BLE001
            errors.append({"ticker": ticker, "error": str(exc)})
            continue
        if fin.get("net_income") is None and fin.get("revenue") is None:
            continue
        c = catalogue_storage.get_catalog_conn()
        with c:
            c.execute(
                """
                INSERT INTO catalog_financials
                    (ticker, form, year, quarter, revenue, gross_profit, cash,
                     total_liabilities, net_income, operating_income)
                VALUES (?, 'NSBU', ?, ?, ?, NULL, ?, ?, ?, NULL)
                ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET
                    revenue = excluded.revenue, cash = excluded.cash,
                    total_liabilities = excluded.total_liabilities,
                    net_income = excluded.net_income, updated_at = datetime('now')
                """,
                (ticker, r["year"], r["quarter"] or 0, fin.get("revenue"),
                 fin.get("cash"), fin.get("total_liabilities"), fin.get("net_income")),
            )
        c.close()
        updated += 1
        updated_tickers.append(ticker)
    if unresolved:
        # Not an error, but not silent either: these issuers stay uncovered by
        # design because guessing which company a filing belongs to is what
        # produced wrong numbers before.
        catalogue_settings.logger.info("pdf fallback: skipped %d ticker(s) with no resolved org id: %s",
                    len(unresolved), ", ".join(sorted(unresolved)[:20]))
    return {"ok": True, "candidates": len(best), "updated": updated,
            "updated_tickers": updated_tickers,
            "skipped_unresolved": len(unresolved), "errors": errors[:10]}


_PROVENANCE_FIELDS = ("revenue", "gross_profit", "cash", "total_liabilities",
                      "net_income", "operating_income", "total_assets", "equity")


def _register_parse(ticker: str, form: str, year: int, quarter: int | None,

                    data: dict[str, Any] | None, values: dict[str, Any] | None) -> int | None:

    """Move a report through its parse states and record what came out of it.



    Returns the registry id to stamp on the published row, or None when the

    report is not in the registry — in which case the figure is published

    without a source link and SRC-03 will say so, which is the correct outcome:

    a missing link is a finding, not something to paper over.

    """

    try:

        import provenance



        period_type = "annual" if not quarter else "quarter"

        report_id = provenance.report_id_for(ticker, form, period_type, year, quarter)

        # Historical discovery can add a catalog entry after the last registry

        # sync. Register that actual document now; otherwise a successful parse

        # is stored with no source passport until an unrelated maintenance run.

        urls = catalogue_filings.get_report_urls(ticker, form, year, quarter or 0)

        if urls and (urls.get("excel_url") or urls.get("excel_url_form1")):

            issuer = catalogue_filings.get_company_index(ticker) or {}

            report_id = provenance.upsert_report(

                str(issuer.get("org_id") or f"ticker:{ticker}"), form, period_type,

                year, quarter or None, title=urls.get("title"),

                pdf_url=urls.get("pdf_url"),

                excel_url=urls.get("excel_url") or urls.get("excel_url_form1"),

                source_published_at=urls.get("published_at"))

        if report_id is None:

            return None

        if not (data or {}).get("ok"):

            provenance.set_state(report_id, "download_failed",

                                 str((data or {}).get("error") or "источник не отдал файл"))

            return report_id

        provenance.set_state(report_id, "parsed")

        usable = [k for k in _PROVENANCE_FIELDS if (values or {}).get(k) is not None]

        if not usable:

            # We have the report and could not get numbers out of it. That is

            # information, and the report keeps its reason instead of vanishing.

            provenance.set_state(report_id, "parse_failed",

                                 "в отчёте не найдено ни одного показателя")

            return report_id

        provenance.record_figures(report_id, [

            # The parser hands over values without the row they were read from,

            # so `page` and `raw_label` stay empty for now: the traceability this

            # gives today is which filing, form and period — not which line.

            {"field": k, "value": values[k], "unit_scale": catalogue_fields.NSBU_THOUSANDS_UZS}

            for k in usable

        ])

        provenance.set_extraction_version(report_id, "nsbu-financial-parser-v1")

        provenance.set_state(report_id, "validated")

        return report_id

    except Exception:  # noqa: BLE001 — provenance must never break a collection

        catalogue_settings.logger.exception("provenance: could not register parse for %s %s %s", ticker, year, quarter)

        return None


def backfill_report_links(limit: int | None = None, *, seed: bool = True) -> dict[str, int]:

    """Link figures cached BEFORE provenance existed to the report they came from.



    Every row in ``catalog_financials`` was produced by the parse path from the

    filing for its own (ticker, form, year, quarter) — that mapping is

    deterministic, so the link can be recovered without re-downloading anything.

    The figures are recorded and the report is marked validated, because that is

    what actually happened; only the record of it was missing.



    A row whose report is not in the registry is left alone. SRC-03 will report

    it, which is correct: an unlinked figure is a finding, not a gap to fill with

    a guess.



    Resolves and writes in bulk. Row-at-a-time it opened four connections and

    asked the registry a fresh question per cached figure; ``seed`` exists so a

    caller that has just run ``sync_from_catalog`` itself does not pay for it

    twice.

    """

    import provenance



    if seed:

        try:

            provenance.sync_from_catalog()

        except Exception:  # noqa: BLE001

            catalogue_settings.logger.exception("provenance: backfill could not seed the registry")

            return {"linked": 0, "unresolved": 0}



    conn = catalogue_storage.get_catalog_conn()

    try:

        rows = conn.execute(

            "SELECT ticker, form, year, quarter, " + ", ".join(catalogue_financial_store._FINANCIAL_KEYS) + " "

            "FROM catalog_financials WHERE report_id IS NULL"

        ).fetchall()

    finally:

        conn.close()



    index = provenance.report_index()

    linked = unresolved = 0

    figure_items: list[tuple[int, list[dict[str, Any]]]] = []

    validated: list[int] = []

    links: list[tuple] = []

    for row in rows[:limit] if limit else rows:

        quarter = row["quarter"] or None

        period_type = "annual" if not quarter else "quarter"

        report_id = index.get((str(row["ticker"]), str(row["form"]), period_type,

                               int(row["year"]), int(quarter) if quarter else -1))

        if report_id is None:

            unresolved += 1

            continue

        figures = [{"field": k, "value": row[k], "unit_scale": catalogue_fields.NSBU_THOUSANDS_UZS}

                   for k in catalogue_financial_store._FINANCIAL_KEYS if row[k] is not None]

        if figures:

            figure_items.append((report_id, figures))

            validated.append(report_id)

        links.append((report_id, row["ticker"], row["form"], row["year"], row["quarter"]))

        linked += 1



    provenance.record_figures_bulk(figure_items)

    # Several tickers of one issuer resolve to one report; state it once.

    provenance.set_state_bulk(list(dict.fromkeys(validated)), "validated")

    if links:

        conn = catalogue_storage.get_catalog_conn()

        try:

            with conn:

                conn.executemany(

                    "UPDATE catalog_financials SET report_id=? WHERE ticker=? AND form=? "

                    "AND year=? AND quarter=?", links)

        finally:

            conn.close()

    catalogue_settings.logger.info("provenance backfill: linked %d, unresolved %d", linked, unresolved)

    return {"linked": linked, "unresolved": unresolved}


def refresh_financials_cache(tickers: list[str] | None = None, *,
                             form: str = "NSBU",
                             limit: int | None = None,
                             ttl_days: int | None = None,
                             sync_missing: bool = True,
                             sync_limit: int | None = None) -> dict[str, Any]:
    """Lazily fill the financials cache for stale/missing tickers, in batches.

    Parses the latest annual NSBU report (form 1 + form 2) for each candidate and
    stores the six headline indicators. When ``sync_missing`` is set and no ticker
    filter is given, first syncs a small batch of not-yet-catalogued companies so a
    fresh backend self-populates over successive calls. Non-blocking: if another
    refresh is already running, returns immediately. Safe to call fire-and-forget
    on every market load — it only processes up to ``limit`` companies per call.
    """
    limit = limit or catalogue_settings.FINANCIALS_BATCH
    ttl_days = ttl_days if ttl_days is not None else catalogue_settings.FINANCIALS_TTL_DAYS
    sync_limit = catalogue_settings.FINANCIALS_SYNC_BATCH if sync_limit is None else sync_limit
    if not catalogue_settings._FIN_LOCK.acquire(blocking=False):
        return {"ok": True, "skipped": "already running", "processed": 0}
    processed = 0
    filled = 0
    synced = 0
    try:
        # Bootstrap the catalog on a fresh backend (only when scanning all tickers).
        if sync_missing and not tickers:
            synced = _sync_missing_companies(form, sync_limit)
        # Register whatever the catalog now knows in the provenance registry, so
        # a report discovered this morning has a state before anyone parses it.
        try:
            import provenance

            provenance.sync_from_catalog()
        except Exception:  # noqa: BLE001 — never block a collection on bookkeeping
            catalogue_settings.logger.exception("provenance: catalog sync failed")
        conn = catalogue_storage.get_catalog_conn()
        candidates = _fin_candidates(conn, form, ttl_days, tickers)
        conn.close()
        for cand in candidates[:limit]:
            ticker, year, quarter = cand["ticker"], cand["year"], cand["quarter"]
            processed += 1
            try:
                data = catalogue_sources.fetch_report_excel_data(ticker, form, year, quarter)
                ratios = catalogue_parsing.compute_financial_ratios(data.get("income"), data.get("balance")) if data.get("ok") else {}
                vals = (ratios.get("source_values") or {}) if ratios else {}
                if not any(vals.get(k) is not None for k in catalogue_financial_store._FINANCIAL_KEYS):
                    # Preferred (annual) report had no usable data — e.g. an old
                    # empty filing. Fall back to the ticker's most recent report.
                    alt = _latest_excel_report(ticker, form, exclude=(year, quarter or 0))
                    if alt:
                        alt_data = catalogue_sources.fetch_report_excel_data(ticker, form, alt["year"], alt["quarter"])
                        if alt_data.get("ok"):
                            alt_ratios = catalogue_parsing.compute_financial_ratios(alt_data.get("income"), alt_data.get("balance"))
                            alt_vals = alt_ratios.get("source_values") or {}
                            if any(alt_vals.get(k) is not None for k in catalogue_financial_store._FINANCIAL_KEYS):
                                year, quarter, vals, ratios = alt["year"], alt["quarter"], alt_vals, alt_ratios
                # ТЗ Дополнение 1 §Б.2/§Б.3: the report this parse consumed moves
                # through its states and the figures are recorded against it, so
                # every number we publish can name the filing it came from. A
                # failure here is logged and never allowed to stop the parse —
                # provenance is a record of the work, not a precondition for it.
                report_id = _register_parse(ticker, form, year, quarter, data, vals)
                if any(vals.get(k) is not None for k in catalogue_financial_store._FINANCIAL_KEYS):
                    catalogue_financial_store.upsert_financials_cache(ticker, form, year, quarter, vals, report_id)
                    # Cache the ratios computed from the same statements: this is
                    # what fills the company-page Key Metrics block and sector
                    # averages — previously only a manual, login-gated analysis
                    # wrote them, so catalog_ratios stayed empty for everyone.
                    metrics = (ratios or {}).get("metrics") or {}
                    if any(v is not None for v in metrics.values()):
                        catalogue_financial_store.upsert_ratio_cache(ticker, form, year, quarter or 0, metrics)
                    filled += 1
            except Exception:
                catalogue_settings.logger.exception("financials refresh failed for %s", ticker)
        return {"ok": True, "synced": synced, "candidates": len(candidates),
                "processed": processed, "filled": filled}
    finally:
        catalogue_settings._FIN_LOCK.release()
