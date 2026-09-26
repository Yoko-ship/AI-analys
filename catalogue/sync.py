"""Coordinate issuer discovery and filing synchronization."""
from __future__ import annotations
import catalogue.ratios as catalogue_ratios
import catalogue.snapshots as catalogue_snapshots
import requests
from typing import Any
import sqlite3

import catalogue.filings as catalogue_filings
import catalogue.periods as catalogue_periods
import catalogue.settings as catalogue_settings
import catalogue.sources as catalogue_sources
import catalogue.storage as catalogue_storage
import re


def sync_company(

    ticker: str,

    company_name: str,

    *,

    force: bool = False,

    org_id: str | None = None,

) -> dict[str, Any]:

    conn = catalogue_storage.get_catalog_conn()



    # Check freshness unless forced

    if not force:

        row = conn.execute(

            "SELECT last_synced_at FROM catalog_companies WHERE ticker = ?", (ticker,)

        ).fetchone()

        if row and catalogue_periods._is_fresh(row["last_synced_at"]):

            conn.close()

            return {"ticker": ticker, "skipped": True}



    session = catalogue_sources._make_session()

    errors: list[str] = []

    added = 0



    # Resolution precedence: explicit caller org (already override-aware) →

    # ORG_OVERRIDES → deterministic ticker/ISIN index → name matching (last

    # resort, confidence-floored). A below-confidence resolution returns

    # nothing and is recorded as sync_error — wrong data is never landed.

    try:

        from entity_resolver import ORG_OVERRIDES, resolve_by_index



        resolved_name = company_name

        if not org_id:

            org_id = ORG_OVERRIDES.get(ticker.upper())

        if not org_id:

            try:

                hit = resolve_by_index(ticker, session=session)

            except Exception:  # noqa: BLE001 — index needs network; fall through

                hit = None

            if hit:

                org_id = hit["org_id"]

                resolved_name = hit.get("org_name") or company_name

        if not org_id:

            company = catalogue_sources.resolve_company(company_name, session=session)

            org_id = company.get("org_id")

            resolved_name = company.get("company_name") or company_name

        # Preferred share tickers (e.g. AGBAP) share the same org as the base ticker (AGBA).

        # If resolution failed, retry with the base ticker's company name.

        if not org_id and ticker.endswith("P"):

            base_name = catalogue_settings._TICKER_TO_NAME.get(ticker[:-1])

            if base_name and base_name != company_name:

                company = catalogue_sources.resolve_company(base_name, session=session)

                org_id = company.get("org_id")

                resolved_name = company.get("company_name") or resolved_name

        if not org_id:

            raise LookupError(f"No org_id for {company_name!r}")

    except Exception as exc:

        err = str(exc)

        errors.append(err)

        with conn:

            conn.execute(

                """

                INSERT INTO catalog_companies (ticker, company_name, last_synced_at, sync_error)

                VALUES (?,?,datetime('now'),?)

                ON CONFLICT(ticker) DO UPDATE SET sync_error=excluded.sync_error, last_synced_at=datetime('now')

                """,

                (ticker, company_name, err),

            )

        conn.close()

        return {"ticker": ticker, "org_id": None, "added": 0, "errors": errors}

    org_id = str(org_id)

    company_name = resolved_name



    # Self-healing: if this ticker previously pointed at a different org, its

    # stored reports/financials/ratios belong to that other company — purge

    # them so only the correct issuer's data is (re-)landed below.

    prev = conn.execute(

        "SELECT org_id FROM catalog_companies WHERE ticker = ?", (ticker,)

    ).fetchone()

    if prev and prev["org_id"] and str(prev["org_id"]) != org_id:

        catalogue_settings.logger.warning(

            "%s: issuer org changed %s -> %s; purging previously stored data",

            ticker, prev["org_id"], org_id,

        )

        with conn:

            catalogue_filings._purge_ticker_data(conn, ticker)



    base = f"/reports/accounting-report/{org_id}/"



    # Fetch the /reports/main/ listing up front: it supplies the issuer's

    # org_type (needed to build NSBU Excel export URLs) and the MSFO/Audition

    # records consumed further below. openinfo's search misses the full legal

    # name for many issuers, so _fetch_main_results retries with cleaner terms.

    try:

        main_results, org_type = catalogue_sources._fetch_main_results(session, company_name, org_id)

    except Exception as exc:

        main_results, org_type = [], None

        errors.append(f"reports/main: {exc}")

    try:

        from financial_ingestion.disclosures import remember_listing

        remember_listing(ticker=ticker, org_id=org_id, records=main_results)

    except Exception as exc:

        errors.append(f"annual attachment discovery: {exc}")

    try:

        catalogue_snapshots._remember_ifrs_sources(ticker=ticker, org_id=org_id, records=main_results)

    except Exception as exc:

        errors.append(f"IFRS source discovery: {exc}")



    # ---- NSBU annual -------------------------------------------------------

    try:

        form2_annual = catalogue_sources._json_get(session, base, {"accounting_type": "form2", "report_type": "annual"})

        if not isinstance(form2_annual, list):

            form2_annual = []

    except Exception as exc:

        form2_annual = []

        errors.append(f"NSBU annual form2: {exc}")



    try:

        form1_annual = catalogue_sources._json_get(session, base, {"accounting_type": "form1", "report_type": "annual"})

        if not isinstance(form1_annual, list):

            form1_annual = []

    except Exception as exc:

        form1_annual = []

        errors.append(f"NSBU annual form1: {exc}")



    # The /reports/main/ search couldn't resolve org_type for this issuer, so the

    # NSBU Excel URLs below would all come out empty (→ no financials). Recover it

    # by probing the export endpoint against a real report id.

    if org_type is None and form2_annual:

        org_type = catalogue_sources._probe_org_type(session, form2_annual, "annual")



    # The to_pdf id space (see _nsbu_export_urls). Stored NSBU pdf links are

    # cleared first: every one written before this map existed points at some

    # other issuer's document, and _upsert_report COALESCEs a NULL pdf_url with

    # the stored one — the wrong links would survive every re-sync otherwise.

    pdf_ids = catalogue_sources._unified_pdf_id_map(session, org_id)

    with conn:

        conn.execute("UPDATE catalog_reports SET pdf_url = NULL "

                     "WHERE ticker = ? AND report_form = 'NSBU'", (ticker,))



    def _corrected_annuals(records: list[dict]) -> list[tuple[int, str, dict]]:

        """(fiscal year, pub_date, record), source mislabels repaired.



        Two records can land on the same corrected year (a filing and its

        re-upload or revision — YGSY's preliminary FY2024, IPKY's revised

        FY2023): sorting by (year, pub_date) lets the NEWEST publication

        upsert last and win, deterministically.

        """

        out: list[tuple[int, str, dict]] = []

        for rec in records:

            labeled = rec.get("reporting_year")

            if not isinstance(labeled, int):

                continue

            rid = str(rec.get("id") or "")

            if (str(org_id), rid) in catalogue_sources._ANNUAL_RECORD_EXCLUSIONS:

                continue

            pub = (pdf_ids.get(rid) or {}).get("pub_date")

            from nsbu_periods import resolve_annual_year

            reviewed_year = resolve_annual_year(org_id, rid, labeled)

            yr = reviewed_year if reviewed_year is not None else catalogue_periods._effective_annual_year(labeled, pub)

            if catalogue_periods._is_premature_annual_year(yr):

                # openinfo lists a placeholder "annual" for the in-progress fiscal

                # year (e.g. FY2026 mid-2026) whose export is a duplicate of, or an

                # incomplete stand-in for, the prior year. Ingesting it as the newest

                # annual dates the headline figures a year forward — skip it.

                continue

            out.append((yr, str(pub or ""), rec))

        out.sort(key=lambda t: (t[0], t[1]))

        return out



    # Index form1 by CORRECTED fiscal year: the form1 record of a filing carries

    # the same mislabel as its form2 sibling, so an uncorrected index would pair

    # a relabeled income statement with the wrong year's balance (or none).

    form1_annual_by_year: dict[int, dict] = {}

    for yr, _pub, rec in _corrected_annuals(form1_annual):

        form1_annual_by_year[yr] = catalogue_sources._build_report_document(rec)



    annual_years: set[int] = set()

    moved_labels: set[int] = set()

    with conn:

        for yr, pub, rec in _corrected_annuals(form2_annual):

            doc2 = catalogue_sources._build_report_document(rec)

            doc1 = form1_annual_by_year.get(yr)

            pdf_url, excel_url = catalogue_sources._nsbu_export_urls(

                doc2.get("id"), "annual", org_type,

                pdf_id=(pdf_ids.get(str(doc2.get("id") or "")) or {}).get("pdf_id"))

            excel_url_form1 = catalogue_sources._nsbu_export_urls(doc1.get("id"), "annual", org_type)[1] if doc1 else None

            new = catalogue_filings._upsert_report(

                conn, ticker,

                report_form="NSBU",

                period_type="annual",

                year=yr,

                quarter=0,

                title=doc2.get("title"),

                published_at=doc2.get("published_at") or (pub or None),

                pdf_url=pdf_url,

                excel_url=excel_url,

                excel_url_form1=excel_url_form1,

                openinfo_report_id=str(doc2.get("id") or ""),

                object_id=str(doc2.get("object_id") or ""),

            )

            if new:

                added += 1

            annual_years.add(yr)

            if rec.get("reporting_year") != yr:

                moved_labels.add(int(rec["reporting_year"]))



        # A year that exists only as a mislabel is a ghost: before the correction

        # existed, UZHM's FY2024 annual (labeled "2025") was catalogued — and its

        # financials cached — under 2025, a year no record claims once the label

        # is repaired. Rows under such years would sit next to the corrected ones

        # forever (this cache is pruned by nothing else) and render as a duplicate

        # column on the Финансы tab. Scoped to labels seen in THIS response, so a

        # partial fetch can never sweep unrelated history.

        stale_years = sorted(moved_labels - annual_years)

        if stale_years and form2_annual:

            marks = ",".join("?" for _ in stale_years)

            conn.execute(

                f"DELETE FROM catalog_reports WHERE ticker=? AND report_form='NSBU' "

                f"AND period_type='annual' AND year IN ({marks})",

                (ticker, *stale_years))

            conn.execute(

                f"DELETE FROM catalog_financials WHERE ticker=? AND form='NSBU' "

                f"AND quarter=0 AND year IN ({marks})",

                (ticker, *stale_years))

            conn.execute(

                f"DELETE FROM catalog_ratios WHERE ticker=? AND form='NSBU' "

                f"AND quarter=0 AND year IN ({marks})",

                (ticker, *stale_years))

            catalogue_settings.logger.info("%s: pruned mislabel-only annual years %s", ticker, stale_years)

            catalogue_ratios.invalidate_ratios_cache()



    # ---- NSBU quarterly ----------------------------------------------------

    try:

        form2_quarter = catalogue_sources._json_get(session, base, {"accounting_type": "form2", "report_type": "quarter"})

        if not isinstance(form2_quarter, list):

            form2_quarter = []

    except Exception as exc:

        form2_quarter = []

        errors.append(f"NSBU quarter form2: {exc}")



    try:

        form1_quarter = catalogue_sources._json_get(session, base, {"accounting_type": "form1", "report_type": "quarter"})

        if not isinstance(form1_quarter, list):

            form1_quarter = []

    except Exception as exc:

        form1_quarter = []

        errors.append(f"NSBU quarter form1: {exc}")



    # Index form1 quarterly by (year, quarter)

    form1_quarter_by_yq: dict[tuple[int, int], dict] = {}

    for rec in form1_quarter:

        period_str = str(rec.get("period") or "")

        yr = rec.get("reporting_year")

        q = catalogue_periods._extract_quarter(period_str)

        if isinstance(yr, int) and q:

            doc = catalogue_sources._build_report_document(rec)

            form1_quarter_by_yq[(yr, q)] = doc



    # Fall back to a quarterly report id if the issuer files no annuals but the

    # org_type still hasn't been resolved.

    if org_type is None and form2_quarter:

        org_type = catalogue_sources._probe_org_type(session, form2_quarter, "quarter")



    with conn:

        for rec in form2_quarter:

            period_str = str(rec.get("period") or "")

            yr = rec.get("reporting_year")

            q = catalogue_periods._extract_quarter(period_str)

            if not isinstance(yr, int) or not q:

                continue

            doc2 = catalogue_sources._build_report_document(rec)

            doc1 = form1_quarter_by_yq.get((yr, q))

            pdf_url, excel_url = catalogue_sources._nsbu_export_urls(

                doc2.get("id"), "quarter", org_type,

                pdf_id=(pdf_ids.get(str(doc2.get("id") or "")) or {}).get("pdf_id"))

            excel_url_form1 = catalogue_sources._nsbu_export_urls(doc1.get("id"), "quarter", org_type)[1] if doc1 else None

            new = catalogue_filings._upsert_report(

                conn, ticker,

                report_form="NSBU",

                period_type="quarter",

                year=yr,

                quarter=q,

                title=doc2.get("title"),

                # The accounting feed carries no publication date, and the annual

                # path already falls back to the unified feed's for exactly that

                # reason — the quarterly path did not, so every quarter synced

                # through the structured endpoint had NO date at all. That is the

                # date the market-events timeline is ordered by, so the newest

                # filings on the site were the undated ones.

                published_at=(doc2.get("published_at")

                              or (pdf_ids.get(str(doc2.get("id") or "")) or {}).get("pub_date")),

                pdf_url=pdf_url,

                excel_url=excel_url,

                excel_url_form1=excel_url_form1,

                openinfo_report_id=str(doc2.get("id") or ""),

                object_id=str(doc2.get("object_id") or ""),

            )

            if new:

                added += 1



    # ---- NSBU fallback from /reports/main/ ---------------------------------

    # Some issuers (microfinance MCHJ, some LLCs) file NSBU but the structured

    # /reports/accounting-report/{org}/ endpoint returns 400 for them. Their NSBU

    # documents still appear in /reports/main/ with a usable Excel export, so when

    # the structured path yielded nothing we harvest NSBU straight from the listing.

    if not form2_annual and not form2_quarter:

        nsbu_main = [r for r in main_results if r.get("report_type") == "NSBU"]

        with conn:

            for rec in nsbu_main:

                doc = catalogue_sources._build_report_document(rec)

                yr = catalogue_periods._extract_year(rec)

                if not isinstance(yr, int):

                    continue

                pt = str(doc.get("period_type") or "annual").lower()

                if pt not in ("annual", "quarter"):

                    pt = "annual"

                q = 0

                if pt == "quarter":

                    props = rec.get("properties") or {}

                    q = catalogue_periods._extract_quarter(str(props.get("report_title") or "")) or 0

                new = catalogue_filings._upsert_report(

                    conn, ticker,

                    report_form="NSBU",

                    period_type=pt,

                    year=yr,

                    quarter=q,

                    title=doc.get("title"),

                    published_at=doc.get("published_at"),

                    pdf_url=doc.get("pdf_url"),

                    excel_url=doc.get("excel_url"),

                    excel_url_form1=None,

                    openinfo_report_id=str(doc.get("id") or ""),

                    object_id=str(doc.get("object_id") or ""),

                )

                if new:

                    added += 1



    # ---- MSFO + Audition from the /reports/main/ listing fetched above -------

    msfo_results = [r for r in main_results if r.get("report_type") in {"MSFO", "Audition"}]

    with conn:

        for rec in msfo_results:

            doc = catalogue_sources._build_report_document(rec)

            form = doc.get("report_form") or rec.get("report_type")

            if form not in ("MSFO", "Audition"):

                continue

            pt = str(doc.get("period_type") or "annual").lower()

            if pt == "quarterly":

                pt = "quarter"

            yr = catalogue_periods._extract_year(rec)

            if form == "MSFO" and pt == "annual":

                from ifrs_financials import reviewed_catalog_year

                yr = reviewed_catalog_year(conn, org_id, doc.get("pdf_url"), yr)

            q = 0

            if pt == "quarter":

                props = rec.get("properties") or {}

                period_str = str(props.get("report_title") or "")

                q = catalogue_periods._extract_quarter(period_str) or 0

            new = catalogue_filings._upsert_report(

                conn, ticker,

                report_form=form,

                period_type=pt if pt in ("annual", "quarter") else "annual",

                year=yr,

                quarter=q,

                title=doc.get("title"),

                published_at=doc.get("published_at"),

                pdf_url=doc.get("pdf_url"),

                excel_url=doc.get("excel_url"),

                excel_url_form1=None,

                openinfo_report_id=str(doc.get("id") or ""),

                object_id=str(doc.get("object_id") or ""),

            )

            if new:

                added += 1



    # ---- Update company row -------------------------------------------------

    # Partial failures are recorded, not masked: a run where every report fetch

    # errored used to be stamped as a clean sync and stayed invisible for the

    # whole freshness window.

    sync_error = ("; ".join(errors))[:1000] if errors else None

    with conn:

        conn.execute(

            """

            INSERT INTO catalog_companies (ticker, company_name, org_id, last_synced_at, sync_error)

            VALUES (?,?,?,datetime('now'),?)

            ON CONFLICT(ticker) DO UPDATE SET

                company_name   = excluded.company_name,

                org_id         = excluded.org_id,

                last_synced_at = datetime('now'),

                sync_error     = excluded.sync_error

            """,

            (ticker, company_name, org_id, sync_error),

        )



    conn.close()

    return {"ticker": ticker, "org_id": org_id, "added": added, "errors": errors}


def _sync_auditions(conn: sqlite3.Connection, session: Any) -> int:

    """Fetch all /reports/audition/ records and upsert for known org_ids."""

    from collectors.openinfo.settings import OPENINFO_WEB_BASE



    # Build reverse map: org_id (str) → ticker from already-synced companies

    org_to_ticker: dict[str, str] = {

        str(row["org_id"]): row["ticker"]

        for row in conn.execute(

            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL"

        ).fetchall()

    }

    if not org_to_ticker:

        return 0



    added = 0

    page = 1

    while True:

        try:

            payload = catalogue_sources._json_get(session, "/reports/audition/", {"page": page, "page_size": 200})

        except Exception as exc:

            catalogue_settings.logger.warning("audition page %d failed: %s", page, exc)

            break

        results = payload.get("results") or []

        if not results:

            break

        with conn:

            for rec in results:

                org_id_str = str(rec.get("organization") or "")

                ticker = org_to_ticker.get(org_id_str)

                if not ticker:

                    continue

                pdf_file = rec.get("pdf_file") or ""

                pdf_url = f"{OPENINFO_WEB_BASE}/media/{pdf_file}" if pdf_file else None

                title_raw = rec.get("title") or ""

                yr = None

                m = re.search(r"\b(20[12]\d)\b", title_raw)

                if m:

                    yr = int(m.group(1))

                new = catalogue_filings._upsert_report(

                    conn, ticker,

                    report_form="Audition",

                    period_type="annual",

                    year=yr,

                    quarter=0,

                    title=title_raw,

                    published_at=rec.get("pub_date"),

                    pdf_url=pdf_url,

                    excel_url=None,

                    excel_url_form1=None,

                    openinfo_report_id=str(rec.get("id") or ""),

                    object_id=None,

                )

                if new:

                    added += 1

        if len(results) < 200:

            break

        page += 1



    return added


_DETERMINISTIC_RESOLVERS = {"override", "ticker", "isin", "base_ticker_index"}


def discover_and_upsert_securities() -> dict[str, Any]:
    """Discover every UZSE-listed security and record its resolved issuer org.

    This is the self-discovering replacement for iterating the hardcoded
    COMPANY_CATALOG: it upserts a catalog_companies row (ticker -> org_id) for
    *every* listed security — ordinary, preferred and bond — so downstream
    financials inheritance can reach all of them. Deterministic resolutions
    (ticker/ISIN/override) may correct a previously stored org — purging the
    old org's landed data — while name-based matches only fill blanks.
    """
    import entity_resolver as er

    session = catalogue_sources._make_session()
    recs = er.resolve_all(session=session)
    conn = catalogue_storage.get_catalog_conn()
    upserted = 0
    corrected = 0
    with conn:
        for rec in recs:
            org_id = rec.get("org_id")
            name = rec.get("org_name") or rec.get("name") or rec["ticker"]
            deterministic = org_id and rec.get("resolved_by") in _DETERMINISTIC_RESOLVERS
            if deterministic:
                prev = conn.execute(
                    "SELECT org_id FROM catalog_companies WHERE ticker = ?", (rec["ticker"],)
                ).fetchone()
                if prev and prev["org_id"] and str(prev["org_id"]) != str(org_id):
                    catalogue_settings.logger.warning(
                        "%s: issuer org corrected %s -> %s (%s); purging stored data",
                        rec["ticker"], prev["org_id"], org_id, rec.get("resolved_by"),
                    )
                    catalogue_filings._purge_ticker_data(conn, rec["ticker"])
                    corrected += 1
                conn.execute(
                    """
                    INSERT INTO catalog_companies (ticker, company_name, org_id)
                    VALUES (?,?,?)
                    ON CONFLICT(ticker) DO UPDATE SET
                        org_id = excluded.org_id,
                        company_name = COALESCE(NULLIF(catalog_companies.company_name, ''), excluded.company_name)
                    """,
                    (rec["ticker"], name, org_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO catalog_companies (ticker, company_name, org_id)
                    VALUES (?,?,?)
                    ON CONFLICT(ticker) DO UPDATE SET
                        org_id = COALESCE(catalog_companies.org_id, excluded.org_id),
                        company_name = COALESCE(NULLIF(catalog_companies.company_name, ''), excluded.company_name)
                    """,
                    (rec["ticker"], name, org_id),
                )
            upserted += 1
    conn.close()
    queued = 0
    try:
        import company_imports

        queued = len(company_imports.record_discovered_candidates(
            recs, actor="catalog discovery"))
    except Exception:  # noqa: BLE001 — operational discovery must still finish
        catalogue_settings.logger.exception("company import queue update failed")
    resolved = sum(1 for r in recs if r.get("org_id"))
    orgs = {r["org_id"] for r in recs if r.get("org_id")}
    return {"discovered": len(recs), "resolved": resolved, "distinct_orgs": len(orgs),
            "upserted": upserted, "corrected": corrected, "queued": queued,
            "records": recs}


def sync_all(tickers: list[str] | None = None, *, force: bool = False) -> dict[str, Any]:

    with catalogue_settings._SYNC_LOCK:

        discovered_recs: list[dict[str, Any]] = []

        if tickers:

            targets = tickers

        else:

            # Self-discovering path: resolve every listed security, then sync one

            # representative ticker per distinct issuer org (prefs/bonds inherit via

            # get_all_financials, so we don't re-fetch the same issuer per ticker).

            try:

                disc = discover_and_upsert_securities()

                discovered_recs = disc.get("records") or []

                catalogue_settings.logger.info("Discovery: %s", {k: disc[k] for k in ("discovered", "resolved", "distinct_orgs")})

            except requests.RequestException as exc:

                # The live securities feed is optional; the catalog is the fallback.

                catalogue_settings.logger.warning("Security discovery unavailable (%s); using COMPANY_CATALOG", exc)

            except Exception:

                catalogue_settings.logger.exception("Security discovery failed; falling back to COMPANY_CATALOG")

            if discovered_recs:

                seen_orgs: set[str] = set()

                reps: list[str] = []

                # Prefer the name-resolved (ordinary) ticker as the org representative.

                for rec in sorted(discovered_recs, key=lambda r: r.get("resolved_by") == "base_ticker"):

                    org = rec.get("org_id")

                    if not org or org in seen_orgs:

                        continue

                    seen_orgs.add(org)

                    reps.append(rec["ticker"])

                targets = reps or list(catalogue_settings._TICKER_TO_NAME.keys())

            else:

                targets = list(catalogue_settings._TICKER_TO_NAME.keys())



        total = len(targets)

        synced = 0

        skipped = 0

        all_errors: list[dict] = []



        try:

            _conn = catalogue_storage.get_catalog_conn()

            catalogue_filings._cleanup_old_notifications(_conn)

            _conn.commit()

            _conn.close()

        except Exception:

            pass



        # ticker -> name/org from discovery (falls back to the curated catalog name).

        disc_name = {r["ticker"]: (r.get("org_name") or r.get("name")) for r in discovered_recs}

        disc_org = {

            r["ticker"]: str(r["org_id"])

            for r in discovered_recs

            if r.get("org_id") and r.get("resolved_by") in _DETERMINISTIC_RESOLVERS

        }



        for ticker in targets:

            # Skip preferred share tickers (e.g. AGBAP) — they map to the same

            # org on openinfo as their base ticker (AGBA) and would duplicate reports.

            if ticker.endswith("P") and ticker[:-1] in catalogue_settings._TICKER_TO_NAME:

                skipped += 1

                continue

            name = disc_name.get(ticker) or catalogue_settings._TICKER_TO_NAME.get(ticker, ticker)

            try:

                result = sync_company(ticker, name, force=force, org_id=disc_org.get(ticker))

                if result.get("skipped"):

                    skipped += 1

                else:

                    synced += 1

                    if result.get("errors"):

                        all_errors.append({"ticker": ticker, "errors": result["errors"]})

            except Exception as exc:

                all_errors.append({"ticker": ticker, "errors": [str(exc)]})



        # Sync audit reports globally (endpoint has no org_id filter)

        try:

            conn = catalogue_storage.get_catalog_conn()

            session = catalogue_sources._make_session()

            audit_added = _sync_auditions(conn, session)

            conn.close()

            catalogue_settings.logger.info("Audition sync added %d records", audit_added)

        except Exception as exc:

            all_errors.append({"ticker": "_audition", "errors": [str(exc)]})



        # NSBU pdf links can only be rebuilt for issuers whose org resolves —

        # a ticker stuck without one keeps whatever is stored, and every link

        # stored before the feed-id map existed points at some OTHER issuer's

        # document (see _nsbu_export_urls). For those, no download button is

        # better than a wrong document; the link returns when resolution does.

        try:

            conn = catalogue_storage.get_catalog_conn()

            with conn:

                cur = conn.execute(

                    """

                    UPDATE catalog_reports SET pdf_url = NULL

                    WHERE report_form = 'NSBU' AND pdf_url IS NOT NULL

                      AND ticker NOT IN (

                          SELECT ticker FROM catalog_companies

                          WHERE org_id IS NOT NULL AND org_id != ''

                      )

                    """)

                if cur.rowcount:

                    catalogue_settings.logger.info("cleared %d NSBU pdf links for unresolved issuers", cur.rowcount)

            conn.close()

        except Exception:

            catalogue_settings.logger.exception("stale NSBU pdf-link cleanup failed")



        return {

            "total": total,

            "synced": synced,

            "skipped": skipped,

            "errors": all_errors,

        }


def sync_recent_filings(hours: int = 12, *, force: bool = False) -> dict[str, Any]:
    """Re-sync only the issuers openinfo's filing feed says have just filed.

    The full sweep resolves every listed security against openinfo and is minutes
    of upstream traffic; the feed answers "who filed since when" in one request,
    and on a quiet hour the answer is nobody. That is what makes this cheap
    enough to run on a schedule — which is the whole point, because until it did,
    the report catalog only ever moved when somebody pressed «Синхронизировать
    всё». It had not been pressed since 21 July, so fifty issuers' half-year
    reports — filed between 13 July and 5 August — were simply not on the site.

    Stateless, like the filings watcher it reads from: no watermark, no cursor.
    The window is deliberately wider than the interval it runs on, so a missed
    tick heals itself on the next one instead of leaving a hole.
    """
    # Lazy: reports_watch pulls in the openinfo client stack, and this module is
    # imported by the API on every boot.
    from reports_watch import recent_filings

    filings = recent_filings(hours=hours)
    orgs = {str(f.get("organization")) for f in filings if f.get("organization") is not None}
    result: dict[str, Any] = {"hours": hours, "filings": len(filings),
                              "orgs": len(orgs), "targets": [], "synced": 0,
                              "skipped": 0, "errors": []}
    if not orgs:
        return result

    conn = catalogue_storage.get_catalog_conn()
    rows = conn.execute(
        "SELECT ticker, company_name, org_id FROM catalog_companies "
        "WHERE org_id IS NOT NULL AND org_id <> ''").fetchall()
    conn.close()
    members: dict[str, list[Any]] = {}
    for r in rows:
        members.setdefault(str(r["org_id"]).strip(), []).append(r)

    # One sync per ISSUER, under the ticker its catalog entry is listed by. An
    # issuer we have never catalogued has no org_id to match on and is left to
    # the full sweep, which is what discovers new issuers in the first place.
    for org in sorted(orgs & set(members)):
        group = members[org]
        canonical = catalogue_filings._canonical_ticker(r["ticker"] for r in group)
        row = next(r for r in group if r["ticker"] == canonical)
        result["targets"].append(canonical)
        try:
            outcome = sync_company(canonical, row["company_name"] or canonical,
                                   force=force, org_id=org)
            if outcome.get("skipped"):
                result["skipped"] += 1
            else:
                result["synced"] += 1
                if outcome.get("errors"):
                    result["errors"].append({"ticker": canonical, "errors": outcome["errors"]})
        except Exception as exc:  # noqa: BLE001 — one issuer must not stop the rest
            catalogue_settings.logger.exception("filing-driven catalog sync failed for %s", canonical)
            result["errors"].append({"ticker": canonical, "errors": [str(exc)]})
    return result


def _sweep_representatives() -> list[dict[str, Any]]:
    """One entry per issuer, under the ticker its catalog entry is listed by."""
    conn = catalogue_storage.get_catalog_conn()
    try:
        rows = conn.execute(
            "SELECT ticker, company_name, org_id, last_synced_at FROM catalog_companies").fetchall()
    finally:
        conn.close()
    groups: dict[str, list[Any]] = {}
    for r in rows:
        groups.setdefault(str((r["org_id"] or "").strip() or r["ticker"]), []).append(r)
    out = []
    for members in groups.values():
        canonical = catalogue_filings._canonical_ticker(m["ticker"] for m in members)
        row = next(m for m in members if m["ticker"] == canonical)
        out.append(dict(row))
    return out


def sync_stale_companies(limit: int = 8, older_than_hours: float = 24.0) -> dict[str, Any]:
    """Refresh the few issuers that have gone longest without a sync.

    The safety net under the filing feed, and the reason a pass can be cut short
    without leaving a hole: whatever a redeploy interrupted is simply the stalest
    thing next time. Bounded on purpose — a pass that takes minutes is a pass a
    deploy can interrupt, and the hourly cadence covers sixty-six issuers in a
    working day either way.
    """
    result: dict[str, Any] = {"limit": limit, "targets": [], "synced": 0, "errors": []}
    if limit <= 0:
        return result
    stale = [
        r for r in _sweep_representatives()
        if (catalogue_periods._hours_since(r["last_synced_at"]) or float("inf")) >= older_than_hours
    ]
    stale.sort(key=lambda r: str(r["last_synced_at"] or ""))
    for row in stale[:limit]:
        ticker = row["ticker"]
        result["targets"].append(ticker)
        try:
            sync_company(ticker, row["company_name"] or ticker,
                         org_id=str(row["org_id"] or "") or None)
            result["synced"] += 1
        except Exception as exc:  # noqa: BLE001 — one issuer must not stop the rest
            catalogue_settings.logger.exception("stale catalog sync failed for %s", ticker)
            result["errors"].append({"ticker": ticker, "errors": [str(exc)]})
    result["remaining"] = max(0, len(stale) - len(result["targets"]))
    return result
