"""Store and query issuer identities, filing indexes, and synchronization state."""
from __future__ import annotations
from typing import Any
from typing import Iterable
import sqlite3

from company_catalog import COMPANY_SECTORS
from entity_resolver import ORG_OVERRIDES
import catalogue.periods as catalogue_periods
import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage


def _upsert_report(

    conn: sqlite3.Connection,

    ticker: str,

    *,

    report_form: str,

    period_type: str,

    year: int | None,

    quarter: int,

    title: str | None,

    published_at: str | None,

    pdf_url: str | None,

    excel_url: str | None,

    excel_url_form1: str | None,

    openinfo_report_id: str | None,

    object_id: str | None,

) -> bool:

    """Insert or update a report row. Returns True if a new row was inserted."""

    if report_form in {"MSFO", "Audition"} and pdf_url:

        identity = conn.execute(

            "SELECT id FROM catalog_reports WHERE ticker=? AND report_form=? "

            "AND (pdf_url=? OR (openinfo_report_id=? AND openinfo_report_id<>'')) LIMIT 1",

            (ticker, report_form, pdf_url, openinfo_report_id),

        ).fetchone()

        if identity:

            conn.execute(

                "UPDATE catalog_reports SET period_type=?,year=?,quarter=?,title=?,"

                "published_at=COALESCE(?,published_at),pdf_url=?,synced_at=datetime('now') WHERE id=?",

                (period_type, year, quarter, title, published_at, pdf_url, identity["id"]),

            )

            return False

    # Check existence first — SQLite upsert always returns rowcount=1 so we

    # can't distinguish insert vs update from the cursor alone.

    existing = conn.execute(

        "SELECT id FROM catalog_reports WHERE ticker=? AND report_form=? AND period_type=? AND year IS ? AND quarter=?",

        (ticker, report_form, period_type, year, quarter),

    ).fetchone()

    is_new = existing is None



    conn.execute(

        """

        INSERT INTO catalog_reports

            (ticker, report_form, period_type, year, quarter, title,

             published_at, pdf_url, excel_url, excel_url_form1,

             openinfo_report_id, object_id, synced_at)

        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))

        -- Keep a link the new payload does not carry. The existing row must be

        -- named: SQLite reads a bare column here as the stored row, PostgreSQL

        -- cannot tell it from `excluded` and raises AmbiguousColumn — so the

        -- unqualified form does not degrade, it stops the sync dead.

        ON CONFLICT(ticker, report_form, period_type, year, quarter) DO UPDATE SET

            title               = excluded.title,

            -- The structured accounting feed carries no publication date, so an

            -- hourly sync would blank the one the unified feed established —

            -- and the historical-quarter harvest reads that date to tell a

            -- superseded revision from a filing it has never seen. Same rule as

            -- the links below: a payload silent about a field leaves it alone.

            published_at        = COALESCE(excluded.published_at, catalog_reports.published_at),

            pdf_url             = COALESCE(excluded.pdf_url, catalog_reports.pdf_url),

            excel_url           = COALESCE(excluded.excel_url, catalog_reports.excel_url),

            excel_url_form1     = COALESCE(excluded.excel_url_form1, catalog_reports.excel_url_form1),

            openinfo_report_id  = COALESCE(excluded.openinfo_report_id, catalog_reports.openinfo_report_id),

            object_id           = COALESCE(excluded.object_id, catalog_reports.object_id),

            synced_at           = datetime('now')

        """,

        (

            ticker, report_form, period_type, year, quarter, title,

            published_at, pdf_url, excel_url, excel_url_form1,

            openinfo_report_id, object_id,

        ),

    )

    if is_new:

        try:

            conn.execute(

                # detected_at is written EXPLICITLY rather than left to the column

                # default. pg_migrate's type map rewrites `DATETIME` to `TEXT`

                # before it looks for `datetime('now')`, so the default reached

                # PostgreSQL as `DEFAULT (TEXT('now'))` — the literal string «now».

                # 195 of the 199 events in this table on prod carried it, and

                # because "now" sorts above every real date and passes every

                # `>= datetime('now', ?)` window, they pinned themselves to the top

                # of the timeline forever and could never be cleaned up either.

                # The rewrite is fixed too, but a writer that states its own clock

                # cannot be broken by a DDL translation again.

                "INSERT INTO catalog_new_reports "

                "(ticker, report_form, period_type, year, quarter, title, detected_at) "

                "VALUES (?,?,?,?,?,?,datetime('now'))",

                (ticker, report_form, period_type, year, quarter, title),

            )

        except Exception:

            pass

    return is_new


def _cleanup_old_notifications(conn: sqlite3.Connection, days: int = 30) -> None:
    conn.execute(
        "DELETE FROM catalog_new_reports WHERE detected_at < datetime('now', ?)",
        (f"-{days} days",),
    )


def _purge_ticker_data(conn: sqlite3.Connection, ticker: str) -> None:
    """Remove a ticker's landed data (used when its issuer org mapping changes)."""
    for table in ("catalog_reports", "catalog_new_reports", "catalog_financials", "catalog_ratios"):
        conn.execute(f"DELETE FROM {table} WHERE ticker = ?", (ticker,))


def get_state(key: str) -> str | None:
    conn = catalogue_storage.get_catalog_conn()
    try:
        row = conn.execute("SELECT value FROM catalog_state WHERE key = ?", (key,)).fetchone()
    except Exception:  # noqa: BLE001 — a deployment that has not migrated yet
        return None
    finally:
        conn.close()
    return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    conn = catalogue_storage.get_catalog_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO catalog_state (key, value, updated_at) "
                "VALUES (?,?,datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value))
    finally:
        conn.close()


FULL_SWEEP_KEY = "catalog_full_sweep_at"


def full_sweep_age_hours() -> float | None:
    """Hours since the last COMPLETED full sweep, or None if there has been none.

    Recorded rather than derived. The company timestamps cannot answer it: the
    hourly pass refreshes a handful of issuers, so the newest stamp is always
    minutes old, and the oldest belongs to a preferred ticker the sweep skips on
    purpose. And a sweep that a redeploy interrupted must count as not done —
    which is what an unwritten completion says, at no extra cost.
    """
    return catalogue_periods._hours_since(get_state(FULL_SWEEP_KEY))


def _org_siblings(conn, ticker: str) -> list[str]:
    """Every ticker the issuer behind ``ticker`` is listed under.

    An issuer files on openinfo once, as an organisation — but this catalog is
    keyed by ticker, and one issuer can hold several: a common and a preferred
    share (HMKB/HMKBP), or one ticker per bond series (four for AGAT CREDIT).
    The sync then scatters that single set of filings across them, so no ticker
    holds the issuer's complete record: Hamkorbank showed 28 reports under HMKB
    and 29 under HMKBP, only 19 of them the same. ``org_id`` is what says the
    two are one company.
    """
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return []
    row = conn.execute(
        "SELECT org_id FROM catalog_companies WHERE ticker = ?", (ticker,)).fetchone()
    org = str((row["org_id"] if row else "") or "").strip()
    if not org:
        return [ticker]
    rows = conn.execute(
        "SELECT ticker FROM catalog_companies WHERE org_id = ?", (org,)).fetchall()
    return sorted({ticker} | {str(r["ticker"]).upper() for r in rows if r["ticker"]})


def _canonical_ticker(tickers: Iterable[str]) -> str:
    """The one ticker an issuer's catalog entry is listed under.

    A common share outranks its own preferred (HMKB over HMKBP — the P is the
    same company's second class, not a second company); otherwise the first
    alphabetically, which for a bond issuer is an arbitrary but stable choice.
    """
    group = {t for t in tickers if t}
    return sorted(group, key=lambda t: (t.endswith("P") and t[:-1] in group, t))[0]


def _report_key(row: Any) -> tuple:

    """What makes two rows the same filing, whichever ticker they were synced under."""

    if row["year"] is None or (row["period_type"] == "quarter" and not row["quarter"]):

        # Unknown dates are not a shared period: retain each original PDF.

        return (row["report_form"], row["period_type"], row["year"], row["quarter"], row["pdf_url"])

    return (row["report_form"], row["period_type"], row["year"], row["quarter"])


def get_company_index(ticker: str) -> dict[str, Any]:

    import company_imports



    conn = catalogue_storage.get_catalog_conn()

    company_row = conn.execute(

        "SELECT company_name, org_id, last_synced_at FROM catalog_companies WHERE ticker = ?",

        (ticker,),

    ).fetchone()



    # The issuer's whole record, not the share of it that happens to be filed

    # under this ticker.

    siblings = _org_siblings(conn, ticker) or [ticker]

    placeholders = ",".join("?" * len(siblings))

    rows = conn.execute(

        f"""

        SELECT report_form, period_type, year, quarter, title, published_at,

               pdf_url, excel_url, excel_url_form1

        FROM catalog_reports

        WHERE ticker IN ({placeholders})

        ORDER BY year DESC, quarter DESC

        """,

        siblings,

    ).fetchall()

    conn.close()



    # The same filing can be stored under two of the issuer's tickers; keep the

    # copy that carries the most download links.

    from financial_ingestion.publication import catalog_labels

    labels = catalog_labels(ticker)

    best: dict[tuple, Any] = {}

    for r in rows:

        r = {**dict(r), **labels.get(r["pdf_url"], {})}

        key = _report_key(r)

        current = best.get(key)

        links = sum(1 for c in ("pdf_url", "excel_url", "excel_url_form1") if r[c])

        if current is None or links > current[0]:

            best[key] = (links, r)

    reports = [r for _, r in best.values()]



    availability: dict[str, dict[str, list]] = {

        "NSBU": {"annual": [], "quarter": []},

        "MSFO": {"annual": [], "quarter": []},

        "Audition": {"annual": [], "quarter": []},

    }

    years_seen: set[int] = set()



    for r in reports:

        form = r["report_form"]

        pt = r["period_type"]

        yr = r["year"]

        if yr:

            years_seen.add(yr)

        entry = {

            "year": yr,

            "quarter": r["quarter"],

            "title": r["title"],

            "published_at": r["published_at"],

            "has_pdf": bool(r["pdf_url"]),

            "has_excel": bool(r["excel_url"]),

            "has_excel_form1": bool(r["excel_url_form1"]),

            "pdf_url": r["pdf_url"],

            "excel_url": r["excel_url"],

            "excel_url_form1": r["excel_url_form1"],

        }

        bucket = availability.setdefault(form, {"annual": [], "quarter": []})

        bucket.setdefault(pt, []).append(entry)



    imported = company_imports.approved_metadata_map().get(ticker) or {}

    return {

        "ticker": ticker,

        "company_name": (imported.get("company_name")

                         or (company_row["company_name"] if company_row else catalogue_settings._TICKER_TO_NAME.get(ticker, ticker))),

        "sector": imported.get("sector") or COMPANY_SECTORS.get(ticker),

        "org_id": company_row["org_id"] if company_row else None,

        "last_synced_at": company_row["last_synced_at"] if company_row else None,

        # Every ticker of this issuer — the entry stands for all of them.

        "tickers": siblings,

        "availability": availability,

        "years": sorted(years_seen, reverse=True),

        "report_count": len(reports),

    }


def get_report_urls(ticker: str, form: str, year: int, quarter: int) -> dict[str, Any] | None:
    conn = catalogue_storage.get_catalog_conn()
    row = conn.execute(
        """
        SELECT pdf_url, excel_url, excel_url_form1, title, published_at, period_type
        FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND year = ? AND quarter = ?
        """,
        (ticker, form, year, quarter),
    ).fetchone()
    if row is None:
        # The catalog entry stands for the whole issuer, so it offers filings
        # that were synced under a sibling ticker. Ask them too, or every such
        # report would 404 the moment someone clicked it.
        siblings = [t for t in _org_siblings(conn, ticker) if t != (ticker or "").upper().strip()]
        if siblings:
            placeholders = ",".join("?" * len(siblings))
            row = conn.execute(
                f"""
                SELECT pdf_url, excel_url, excel_url_form1, title, published_at, period_type
                FROM catalog_reports
                WHERE ticker IN ({placeholders})
                  AND report_form = ? AND year = ? AND quarter = ?
                ORDER BY (CASE WHEN excel_url IS NOT NULL AND excel_url != '' THEN 0 ELSE 1 END),
                         (CASE WHEN pdf_url   IS NOT NULL AND pdf_url   != '' THEN 0 ELSE 1 END)
                """,
                [*siblings, form, year, quarter],
            ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "pdf_url": row["pdf_url"],
        "excel_url": row["excel_url"],
        "excel_url_form1": row["excel_url_form1"],
        "title": row["title"],
        "published_at": row["published_at"],
        "period_type": row["period_type"],
    }


def list_companies_with_stats() -> list[dict[str, Any]]:
    """One entry per ISSUER, not per ticker.

    The catalog is a list of companies and their filings, and openinfo files by
    organisation — so a company holding several tickers belongs on it once. It
    used to appear once per ticker, which put «AGAT CREDIT» on the page four
    times (one per bond series), each showing a different slice of the same
    filings: 3 reports, 0, 0, 1. The rule that hid a preferred share behind its
    common (HMKB/HMKBP) was the same idea applied to one special case; org_id
    covers both, and it merges the filings instead of discarding one side's.
    """
    conn = catalogue_storage.get_catalog_conn()
    companies = conn.execute(
        "SELECT ticker, company_name, org_id, last_synced_at "
        "FROM catalog_companies ORDER BY ticker").fetchall()
    # DISTINCT over the issuer: the same filing stored under two of its tickers
    # is one report, and summing per-ticker counts would double it.
    filings = conn.execute(
        """
        SELECT DISTINCT
            COALESCE(NULLIF(c.org_id, ''), c.ticker) AS grp,
            r.report_form AS form,
            r.period_type AS pt,
            r.year        AS yr,
            r.quarter     AS qr
        FROM catalog_companies c
        JOIN catalog_reports r ON r.ticker = c.ticker
        """
    ).fetchall()
    conn.close()

    counts: dict[str, dict[str, int]] = {}
    for f in filings:
        bucket = counts.setdefault(str(f["grp"]), {
            "nsbu_count": 0, "msfo_count": 0, "audit_count": 0, "total_count": 0})
        key = {"NSBU": "nsbu_count", "MSFO": "msfo_count", "Audition": "audit_count"}.get(f["form"])
        if key:
            bucket[key] += 1
        bucket["total_count"] += 1

    groups: dict[str, list[Any]] = {}
    for row in companies:
        groups.setdefault(str((row["org_id"] or "").strip() or row["ticker"]), []).append(row)

    out: list[dict[str, Any]] = []
    for grp, members in groups.items():
        canonical = _canonical_ticker(r["ticker"] for r in members)
        row = next(r for r in members if r["ticker"] == canonical)
        synced = [r["last_synced_at"] for r in members if r["last_synced_at"]]
        out.append({
            "ticker": canonical,
            "company_name": row["company_name"],
            "org_id": row["org_id"],
            # The issuer was last seen when any of its tickers was.
            "last_synced_at": max(synced) if synced else None,
            "tickers": sorted(r["ticker"] for r in members),
            **counts.get(grp, {"nsbu_count": 0, "msfo_count": 0,
                               "audit_count": 0, "total_count": 0}),
        })
    out.sort(key=lambda c: c["ticker"])
    return out


def get_catalog_stats() -> dict[str, Any]:
    conn = catalogue_storage.get_catalog_conn()
    # Counted in the unit the company list is built from — the issuer and its
    # distinct filings. Counting rows said "85 companies · 2021 reports" above a
    # list of 73 companies whose own totals add up to fewer.
    totals = conn.execute(
        """
        SELECT
            COUNT(DISTINCT grp) AS companies_synced,
            COUNT(*) AS total_reports,
            SUM(CASE WHEN form = 'NSBU'     THEN 1 ELSE 0 END) AS nsbu,
            SUM(CASE WHEN form = 'MSFO'     THEN 1 ELSE 0 END) AS msfo,
            SUM(CASE WHEN form = 'Audition' THEN 1 ELSE 0 END) AS audit
        FROM (
            SELECT DISTINCT
                COALESCE(NULLIF(c.org_id, ''), r.ticker) AS grp,
                r.report_form AS form,
                r.period_type AS pt,
                r.year        AS yr,
                r.quarter     AS qr
            FROM catalog_reports r
            LEFT JOIN catalog_companies c ON c.ticker = r.ticker
        ) filings
        """
    ).fetchone()
    last_sync = conn.execute(
        "SELECT MAX(last_synced_at) AS ls FROM catalog_companies"
    ).fetchone()
    conn.close()
    return {
        "companies_synced": totals["companies_synced"] or 0,
        "total_reports": totals["total_reports"] or 0,
        "nsbu": totals["nsbu"] or 0,
        "msfo": totals["msfo"] or 0,
        "audit": totals["audit"] or 0,
        "last_sync": last_sync["ls"] if last_sync else None,
    }


def get_recent_new_reports(since_days: int = 120, limit: int = 80) -> list[dict[str, Any]]:
    """Recently detected new report filings across every ticker — the source for
    the public market-news feed (ТЗ §3.2 item 6).

    A row whose ``detected_at`` is not a date is skipped: the literal «now» that
    a broken DDL default wrote sorts above every real timestamp and satisfies
    every window, so it would take the head of the timeline and stay there.
    """
    conn = catalogue_storage.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT ticker, report_form, period_type, year, quarter, title, detected_at
        FROM catalog_new_reports
        WHERE detected_at >= datetime('now', ?)
          AND detected_at LIKE '____-__-__%'
        ORDER BY detected_at DESC
        LIMIT ?
        """,
        (f"-{max(1, since_days)} days", max(1, limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_filings(since_days: int = 120, limit: int = 120,
                       form: str | None = None) -> list[dict[str, Any]]:
    """Filings ordered by the date the ISSUER published them.

    The events timeline used to be ordered by when WE first noticed a filing
    (`catalog_new_reports.detected_at`) — a fact about our sync schedule, not
    about the market, and one that survives a re-sync no better than a cache. The
    issuer's own publication date is the event, it is stored on the filing, and it
    is the same date openinfo prints beside the document.

    Rows with no publication date are left out rather than dated by a fallback: a
    timeline is a claim about WHEN, and «unknown» has no place in it.
    """
    conn = catalogue_storage.get_catalog_conn()
    params: list[Any] = [f"-{max(1, since_days)} days"]
    clause = ""
    if form:
        clause = "AND report_form = ? "
        params.append(form)
    params.append(max(1, limit))
    rows = conn.execute(
        f"""
        SELECT ticker, report_form, period_type, year, quarter, title,
               published_at, pdf_url, excel_url
        FROM catalog_reports
        WHERE published_at IS NOT NULL
          AND published_at LIKE '____-__-__%'
          AND published_at >= datetime('now', ?)
          {clause}
        ORDER BY published_at DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_new_reports_for_tickers(tickers: list[str], since_days: int = 7) -> list[dict[str, Any]]:
    """Return recently detected new reports for the given tickers (used for notifications)."""
    if not tickers:
        return []
    conn = catalogue_storage.get_catalog_conn()
    placeholders = ",".join("?" * len(tickers))
    rows = conn.execute(
        f"""
        SELECT ticker, report_form, period_type, year, quarter, title, detected_at
        FROM catalog_new_reports
        WHERE ticker IN ({placeholders})
          AND detected_at >= datetime('now', ?)
        ORDER BY detected_at DESC
        """,
        (*tickers, f"-{since_days} days"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_company_reports(ticker: str) -> list[dict[str, Any]]:

    """Return all catalog reports for the issuer behind a ticker, newest first.



    By the issuer, not the ticker: the company page and /catalog are looking at

    the same record, and reading it per-ticker made them disagree — 28 filings

    on one page and 38 on the other for the same bank, because ten had been

    synced under its preferred class.

    """

    conn = catalogue_storage.get_catalog_conn()

    siblings = _org_siblings(conn, ticker) or [(ticker or "").upper()]

    placeholders = ",".join("?" * len(siblings))

    rows = conn.execute(f"""

        SELECT report_form, period_type, year, quarter, title, published_at,

               pdf_url, excel_url, excel_url_form1, openinfo_report_id, object_id,

               synced_at

        FROM catalog_reports

        WHERE ticker IN ({placeholders})

        ORDER BY year DESC, quarter DESC, synced_at DESC

    """, siblings).fetchall()

    conn.close()

    from financial_ingestion.publication import catalog_labels

    labels = catalog_labels(ticker)

    best: dict[tuple, tuple[int, dict[str, Any]]] = {}

    for r in rows:

        r = {**dict(r), **labels.get(r["pdf_url"], {})}

        key = _report_key(r)

        links = sum(1 for c in ("pdf_url", "excel_url", "excel_url_form1") if r[c])

        if key not in best or links > best[key][0]:

            best[key] = (links, dict(r))

    return [r for _, r in best.values()]
