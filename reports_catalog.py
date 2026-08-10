from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlencode

from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
from delisted import DELISTED_ISINS, DELISTED_TICKERS
from entity_resolver import ORG_OVERRIDES, UNRELIABLE_FINANCIALS
import dbx
from db import APP_DATA_DIR, sqlite_connect
from openinfo_collector import (
    OPENINFO_API_BASE,
    OPENINFO_WEB_BASE,
    REQUEST_TIMEOUT,
    _build_report_document,
    _json_get,
    _make_session,
    parse_excel_report_document,
    resolve_company,
)

logger = logging.getLogger(__name__)

CATALOG_SYNC_TTL_HOURS = int(os.getenv("CATALOG_SYNC_TTL_HOURS", "6"))
_SYNC_LOCK = threading.Lock()
# Serialize the lazy financials-cache filler so overlapping market loads don't
# parse the same reports concurrently.
_FIN_LOCK = threading.Lock()
FINANCIALS_TTL_DAYS = int(os.getenv("FINANCIALS_TTL_DAYS", "14"))
FINANCIALS_BATCH = int(os.getenv("FINANCIALS_BATCH", "12"))
# How many not-yet-catalogued companies the financials warmup syncs per call, so a
# fresh backend self-populates progressively without a manual full catalog sync.
FINANCIALS_SYNC_BATCH = int(os.getenv("FINANCIALS_SYNC_BATCH", "8"))

# Inverted catalog: ticker → company_name (take first match if duplicates)
_TICKER_TO_NAME: dict[str, str] = {}
for _name, _ticker in COMPANY_CATALOG.items():
    if _ticker not in _TICKER_TO_NAME:
        _TICKER_TO_NAME[_ticker] = _name


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _catalog_db_path() -> str:
    path = APP_DATA_DIR / "reports_catalog.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS catalog_companies (
            ticker          TEXT PRIMARY KEY,
            company_name    TEXT NOT NULL,
            org_id          TEXT,
            last_synced_at  TEXT,
            sync_error      TEXT
        );

        -- What the catalog knows about itself. One row so far: when the last
        -- FULL sweep finished. That cannot be derived from the company stamps —
        -- the hourly pass refreshes a handful, so the newest is always minutes
        -- old, and the oldest belongs to a ticker the sweep skips on purpose.
        CREATE TABLE IF NOT EXISTS catalog_state (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS catalog_reports (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker              TEXT NOT NULL,
            report_form         TEXT NOT NULL,
            period_type         TEXT NOT NULL,
            year                INTEGER,
            quarter             INTEGER NOT NULL DEFAULT 0,
            title               TEXT,
            published_at        TEXT,
            pdf_url             TEXT,
            excel_url           TEXT,
            excel_url_form1     TEXT,
            openinfo_report_id  TEXT,
            object_id           TEXT,
            synced_at           TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(ticker, report_form, period_type, year, quarter)
        );

        CREATE INDEX IF NOT EXISTS idx_cat_ticker ON catalog_reports(ticker);
        CREATE INDEX IF NOT EXISTS idx_cat_year   ON catalog_reports(year);

        CREATE TABLE IF NOT EXISTS catalog_new_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            report_form TEXT NOT NULL,
            period_type TEXT NOT NULL,
            year        INTEGER,
            quarter     INTEGER NOT NULL DEFAULT 0,
            title       TEXT,
            detected_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_cnr_ticker   ON catalog_new_reports(ticker);
        CREATE INDEX IF NOT EXISTS idx_cnr_detected ON catalog_new_reports(detected_at);

        CREATE TABLE IF NOT EXISTS catalog_ratios (
            ticker         TEXT NOT NULL,
            form           TEXT NOT NULL,
            year           INTEGER NOT NULL,
            quarter        INTEGER NOT NULL DEFAULT 0,
            roa            REAL,
            roe            REAL,
            net_margin     REAL,
            debt_ratio     REAL,
            debt_to_equity REAL,
            updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, form, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS catalog_financials (
            ticker            TEXT NOT NULL,
            form              TEXT NOT NULL DEFAULT 'NSBU',
            year              INTEGER NOT NULL,
            quarter           INTEGER NOT NULL DEFAULT 0,
            revenue           REAL,
            gross_profit      REAL,
            cash              REAL,
            total_liabilities REAL,
            net_income        REAL,
            operating_income  REAL,
            updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, form, year, quarter)
        );
        CREATE INDEX IF NOT EXISTS idx_cat_fin_ticker ON catalog_financials(ticker);

        CREATE TABLE IF NOT EXISTS catalog_trade_stats (
            isin              TEXT PRIMARY KEY,
            trade_date        TEXT,
            total_value       REAL,
            total_qty         REAL,
            trade_count       INTEGER,
            avg_price         REAL,
            largest_qty       REAL,
            largest_value     REAL,
            largest_pct_value REAL,
            largest_pct_qty   REAL,
            open_price        REAL,
            high_price        REAL,
            low_price         REAL,
            close_price       REAL,
            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- The exchange's own session quote per security (uzse.uz/isu_infos):
        -- the official close, the previous close it is measured against (which
        -- the exchange CARRIES FORWARD through sessions with no trades, so no
        -- feed of executions can reproduce it) and the session's own totals.
        -- This is what makes the board's change % the exchange's change %, for
        -- every listed security rather than the 78 the /stocks mirror carries.
        CREATE TABLE IF NOT EXISTS catalog_quotes (
            isin               TEXT PRIMARY KEY,
            ticker             TEXT,
            name               TEXT,
            market             TEXT,
            share_type         TEXT,
            trade_date         TEXT,
            close_price        REAL,
            prev_close         REAL,
            prev_close_date    TEXT,
            change_value       REAL,
            change_percent     REAL,
            open_price         REAL,
            high_price         REAL,
            low_price          REAL,
            quantity           REAL,
            turnover           REAL,
            shares_outstanding REAL,
            market_cap         REAL,
            updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- One row per security per SESSION — the exchange's settled daily record.
        --
        -- catalog_quotes above keeps only the latest session, so a series existed
        -- nowhere we could reach: drawing a sparkline meant one live request to
        -- openinfo per ticker, which is why lists of securities had no chart on
        -- them at all. The data was never missing, only discarded — uzse.uz's
        -- quote page publishes its last ~21 settled sessions in a table the
        -- collector already parses and threw away after reading one row from it.
        --
        -- Carried-forward sessions belong here: the exchange repeats a close at
        -- zero quantity when nothing traded, and a flat line IS what the security
        -- did that day. Dropping them would compress calendar time and make a
        -- quiet month look like an active week.
        CREATE TABLE IF NOT EXISTS catalog_quote_history (
            isin         TEXT NOT NULL,
            trade_date   TEXT NOT NULL,
            close_price  REAL,
            change_value REAL,
            quantity     REAL,
            turnover     REAL,
            updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (isin, trade_date)
        );
        CREATE INDEX IF NOT EXISTS idx_quote_history_isin
            ON catalog_quote_history (isin, trade_date);

        -- Exchange-listing registry for issuers that are listed on RFB Tashkent
        -- (openinfo info_rfb.isin_codes) but absent from the live uzse-stock feed
        -- because they have not traded recently. Carries the last-known trade
        -- (from /iuzse/conclusions/) plus shares outstanding so these securities
        -- can still appear on the market board / company page, tagged inactive.
        CREATE TABLE IF NOT EXISTS catalog_listings (
            ticker             TEXT PRIMARY KEY,
            isin               TEXT,
            name               TEXT,
            share_type         TEXT,
            listing_date       TEXT,
            shares_outstanding REAL,
            reference_price    REAL,
            last_price         REAL,
            last_trade_date    TEXT,
            open_price         REAL,
            high_price         REAL,
            low_price          REAL,
            volume             REAL,
            market_cap         REAL,
            updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- openinfo's dividend calendar, mapped onto our tickers (see dividends.py).
        -- The source publishes one market-wide calendar keyed by organization_id
        -- and carries our ticker on barely half its rows, so the mapping is done
        -- once at snapshot time and stored — a company page then reads an indexed
        -- table instead of asking openinfo to resolve "UNVB" as a company name,
        -- which is what used to answer «Дивиденды не объявлялись» for every issuer.
        -- One row per (security, filing): ordinary and preferred lines each get a
        -- copy, because the filing declares both amounts and the page shows the
        -- column that matches the security.
        CREATE TABLE IF NOT EXISTS catalog_dividends (
            ticker            TEXT NOT NULL,
            filing_id         TEXT NOT NULL,
            org_id            TEXT,
            organization      TEXT,
            decision_date     TEXT,
            pub_date          TEXT,
            ordinary_amount   REAL,
            ordinary_percent  REAL,
            ordinary_start    TEXT,
            ordinary_end      TEXT,
            preferred_amount  REAL,
            preferred_percent REAL,
            preferred_start   TEXT,
            preferred_end     TEXT,
            link              TEXT,
            matched_by        TEXT,
            updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, filing_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cat_div_ticker ON catalog_dividends(ticker);

        -- Generic, forward-compatible fact store (scalable-pipeline design).
        -- Any source (adapter) can land any (entity, dataset, field, period) value
        -- without a schema change, so new datasets/fields published in the future
        -- flow in automatically. entity_id is the openinfo org_id (issuer).
        CREATE TABLE IF NOT EXISTS facts (
            entity_id   TEXT NOT NULL,
            dataset     TEXT NOT NULL,
            field       TEXT NOT NULL,
            period      TEXT NOT NULL DEFAULT '',
            value_num   REAL,
            value_text  TEXT,
            unit        TEXT,
            source      TEXT NOT NULL,
            source_url  TEXT,
            fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (entity_id, dataset, field, period, source)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_id, dataset);

        -- §3.11 editorial-news store. We keep only headline + our own LLM-authored
        -- summary + link + metadata — never the source's full article body — which
        -- keeps aggregation inside Uzbek copyright's news-of-the-day / press-review
        -- allowances (see NEWS_MODULE.md). Populated by the news collector (push) /
        -- the search agent; read by GET /api/news/feed and the risk-profile info dim.
        CREATE TABLE IF NOT EXISTS news (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            url             TEXT NOT NULL UNIQUE,
            source          TEXT NOT NULL,
            source_id       TEXT,
            lang            TEXT,
            title           TEXT NOT NULL,
            snippet         TEXT,
            summary_ru      TEXT,
            image_url       TEXT,
            published_at    TEXT,
            collected_at    TEXT NOT NULL DEFAULT (datetime('now')),
            coverage_weight REAL NOT NULL DEFAULT 0.5
        );
        CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);
        CREATE INDEX IF NOT EXISTS idx_news_source    ON news(source_id);

        -- Per-item NLP output (one row per news item). Every value is a statistical/
        -- analytical signal, not a diagnosis (TZ §3.11): 'direction' is a model
        -- estimate the UI must present with a disclaimer.
        CREATE TABLE IF NOT EXISTS news_nlp (
            news_id         INTEGER PRIMARY KEY REFERENCES news(id) ON DELETE CASCADE,
            relevant        INTEGER NOT NULL DEFAULT 0,
            relevance_score REAL,
            type            TEXT,
            tone            TEXT,
            tone_score      REAL,
            impact          TEXT,
            direction       TEXT,
            sectors_json    TEXT,
            reason          TEXT,
            model           TEXT,
            classified_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- News ↔ issuer links (a news item may touch several tickers).
        CREATE TABLE IF NOT EXISTS news_entities (
            news_id  INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
            ticker   TEXT NOT NULL,
            PRIMARY KEY (news_id, ticker)
        );
        CREATE INDEX IF NOT EXISTS idx_news_ent_ticker ON news_entities(ticker);
    """)
    # Columns added after the table shipped (CREATE IF NOT EXISTS won't touch
    # an existing table) — idempotent per-column migration.
    have = set(dbx.columns(conn, "catalog_trade_stats"))
    for col in ("open_price", "high_price", "low_price", "close_price"):
        if col not in have:
            conn.execute(f"ALTER TABLE catalog_trade_stats ADD COLUMN {col} REAL")
    have_news = set(dbx.columns(conn, "news"))
    if "image_url" not in have_news:
        conn.execute("ALTER TABLE news ADD COLUMN image_url TEXT")
    # The site is served in three languages but every summary we stored was Russian, so an
    # English or Uzbek reader got a Russian feed. The classifier writes all three in the one
    # call it already makes (see news_classifier._SYSTEM) — there is no cheaper source:
    # verified 2026-07-29 against real Chrome, its on-device translator has no Uzbek at all
    # (ru->uz, uz->ru and en->uz all report "unavailable"), so the browser can never serve
    # the Uzbek feed. Nullable: rows collected before this exist and are backfilled by
    # `news_collector.py --backfill-translations`.
    for col in ("summary_en", "summary_uz"):
        if col not in have_news:
            conn.execute(f"ALTER TABLE news ADD COLUMN {col} TEXT")
    # The story page's long read: OUR OWN multi-paragraph account of what the source
    # published, in the three UI languages. It exists because a feed teaser is one sentence
    # while the article behind it is five paragraphs, and a reader who opened the story got
    # the sentence. This is still not the source's text — the article is read once, in
    # memory, to write our own summary, and is never stored (see NEWS_MODULE.md's legal
    # invariant). Nullable: rows collected before it exist, and sources with no article page
    # (the rating agencies, openinfo filings) never get one.
    for col in ("detail_ru", "detail_en", "detail_uz"):
        if col not in have_news:
            conn.execute(f"ALTER TABLE news ADD COLUMN {col} TEXT")
    # Per-field period provenance (JSON {field: period}). A financials row is
    # labelled with ONE period, but a few fields can only be sourced from a
    # different one (bank revenue exists in openinfo's indicators and nowhere in
    # the NSBU form). Recording which period each such field came from is what
    # keeps the row honest instead of passing a full-year figure off as a quarter.
    have_fin = set(dbx.columns(conn, "catalog_financials"))
    if "field_periods" not in have_fin:
        conn.execute("ALTER TABLE catalog_financials ADD COLUMN field_periods TEXT")
    # ТЗ Дополнение 1 §Б.4: a published figure names the report it was read from.
    # Until this column was filled, "where did this revenue come from?" had no
    # answer — nobody could say which filing, which form or which period, or
    # whether the number was parsed at all rather than taken off the wrong field.
    # That is the gap the whole FIN group of defects grew out of.
    if "report_id" not in have_fin:
        conn.execute("ALTER TABLE catalog_financials ADD COLUMN report_id INTEGER")
    # The comparative period the same filing prints beside its own figures (NSBU
    # form 2's value1/value2, "за соответствующий период прошлого года" — the
    # reporting period is value3/value4, see openinfo_reconcile.pl_value), as
    # JSON with its own period label. It rides on the row it was filed with
    # rather than becoming a period of its own — the comparative is P&L only, and
    # a row with no balance sheet would be ranked as a period and divide ratios
    # by nothing.
    if "prior_period" not in have_fin:
        conn.execute("ALTER TABLE catalog_financials ADD COLUMN prior_period TEXT")
    # ТЗ мультипликаторов (2026-08-10). Three additions that let the market tab
    # compute what it used to borrow from the indicator feed:
    #   noninterest_income — «е. Итого беспроцентных доходов» (banks): the second
    #     half of the net-margin denominator, interest + non-interest income;
    #   org_type — jsc/bank/insurance/microfinance, the FORM the figures were
    #     read from. P/S is not shown for banks and insurers, margin carries the
    #     bank footnote — the display rules need the form, not a sector guess;
    #   balance_period — JSON {equity_start, equity_end, assets_start,
    #     assets_end} in thousands, from the SAME filing: P/B's denominator and
    #     the averaged base ROE/ROA divide by.
    if "noninterest_income" not in have_fin:
        conn.execute("ALTER TABLE catalog_financials ADD COLUMN noninterest_income REAL")
    if "org_type" not in have_fin:
        conn.execute("ALTER TABLE catalog_financials ADD COLUMN org_type TEXT")
    if "balance_period" not in have_fin:
        conn.execute("ALTER TABLE catalog_financials ADD COLUMN balance_period TEXT")
    conn.commit()


def get_catalog_conn() -> sqlite3.Connection:
    conn = sqlite_connect(_catalog_db_path())
    dbx.ensure_schema(conn, "catalog", _init_schema)
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_year(report: dict[str, Any]) -> int | None:
    props = report.get("properties") or {}
    for field in ("reporting_year", "year"):
        v = props.get(field)
        if v is not None:
            try:
                yr = int(v)
                if 2000 <= yr <= 2100:
                    return yr
            except (TypeError, ValueError):
                pass
    title = str(props.get("report_title") or "")
    m = re.search(r"\b(20[12]\d)\b", title)
    if m:
        return int(m.group(1))
    pub = str(report.get("pub_date") or "")
    if len(pub) >= 4:
        try:
            yr = int(pub[:4])
            pt = str(props.get("report_type") or "annual").lower()
            return yr - 1 if pt == "annual" else yr
        except (TypeError, ValueError):
            pass
    return None


def _extract_quarter(period_str: str) -> int | None:
    """Parse quarter number from strings like 'Q1 2024' or 'I квартал 2024'."""
    m = re.search(r"Q([1-3])", period_str, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"([1-3])\s*квартал", period_str, re.IGNORECASE)
    if m:
        return int(m.group(1))
    roman = {"I": 1, "II": 2, "III": 3}
    m = re.search(r"\b(III|II|I)\b\s*квартал", period_str, re.IGNORECASE)
    if m:
        return roman.get(m.group(1).upper())
    return None


def _period_key(period: str | None) -> tuple[int, int]:
    """Numeric sort key for fact-store period strings ('2025', '2025Q3').

    Replaces lexicographic comparison, under which corrupt periods from the
    source ('2025Q7' > '2025Q3', '2026Q5' > '2026') won every "latest period"
    pick. An annual period ranks above the year's quarters (it is the complete,
    most recently published figure for that year); anything unparseable or with
    an out-of-range quarter ranks below every valid period.
    """
    m = re.fullmatch(r"(\d{4})(?:Q(\d{1,2}))?", str(period or "").strip())
    if not m:
        return (0, 0)
    year = int(m.group(1))
    if m.group(2) is None:
        return (year, 5)  # annual: outranks Q1-Q4 of the same year
    quarter = int(m.group(2))
    if not 1 <= quarter <= 4:
        return (0, 0)  # corrupt source period — never wins
    return (year, quarter)


def _period_months(year: int | None, quarter: int | None) -> int | None:
    """Months of activity a P&L figure for this period covers.

    NSBU quarterly forms are cumulative from 1 January, so a Q2 figure is six
    months and a Q3 figure nine — not three each. Without this the market board
    puts a full prior year, a half year and a quarter in one column and calls them
    comparable. Balance-sheet lines are point-in-time and need no such number.
    """
    if year is None:
        return None
    if not quarter:
        return 12
    return int(quarter) * 3 if 1 <= int(quarter) <= 4 else None


def _is_future_period(year: int | None, quarter: int | None,
                      today: date | None = None) -> bool:
    """True for a period that has not finished yet — one no filing can describe.

    The last line of defence for the period label. openinfo mis-stamps period-ends
    (an annual filed mid-2026 carrying reporting_year=2026-12-31), and a row that
    reaches storage with such a label wins "latest period" forever and hides the
    issuer's real figures behind a quarter that has not happened. Callers reject
    rather than repair: by the time a row is being written, the filing date that
    would let it be dated correctly is no longer at hand.
    """
    if year is None:
        return False
    today = today or datetime.now(timezone.utc).date()
    q = int(quarter or 0)
    if not q:
        return int(year) > _latest_complete_fiscal_year()
    if not 1 <= q <= 4:
        return False  # corrupt quarter, excluded by its own rule
    end_month, end_day = ((3, 31), (6, 30), (9, 30), (12, 31))[q - 1]
    return date(int(year), end_month, end_day) > today


def _latest_complete_fiscal_year() -> int:
    """The most recent fiscal year for which a complete annual report can exist.

    Uzbek issuers file on a calendar fiscal year, so an annual report for year Y
    is only complete once Y has ended. During calendar year N the newest complete
    annual is therefore FY(N-1). openinfo, however, publishes a placeholder
    "annual" for the *current* year (both as an ``/accounting-report/`` record and
    as a ``financial_indicators`` row) that is either an in-progress figure or a
    duplicate of the prior year — treating it as the latest completed annual dates
    the headline figures a year into the future. This is the cutoff that separates
    a real completed annual from that premature one.
    """
    return datetime.now(timezone.utc).year - 1


def _is_premature_annual_year(year: int | None) -> bool:
    """True for an annual report whose fiscal year has not yet ended."""
    return year is not None and year > _latest_complete_fiscal_year()


def _is_premature_annual_period(period: str | None) -> bool:
    """True for a fact-store *annual* period ('2026') whose year is not complete.

    Quarterly periods ('2026Q1') are point-in-time filings and stay valid.
    """
    y, k = _period_key(period)
    return k == 5 and y > _latest_complete_fiscal_year()


def _fact_period_rank(period: str | None) -> tuple[int, int, int]:
    """``_period_key`` with premature annuals demoted below every real period.

    Used only for "latest period" selection over the fact store, and only ever
    compared against other values of this same function — hence the explicit
    tier, which makes the three classes totally ordered:

        tier 0  junk / unparseable  ('2025Q7')
        tier 1  premature annual    (openinfo's current-year placeholder)
        tier 2  a real period

    A premature annual must never beat a real period, but it must still beat junk
    so an issuer whose *only* fact is the placeholder shows that rather than
    nothing. The previous ``(y - 10000, k)`` demotion overshot: it produced a
    negative year, which sorts BELOW junk's ``(0, 0)`` — so an issuer with one
    placeholder and one corrupt period preferred the corrupt one.
    """
    y, k = _period_key(period)
    if (y, k) == (0, 0):
        return (0, 0, 0)
    if k == 5 and y > _latest_complete_fiscal_year():
        return (1, y, k)
    return (2, y, k)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_fresh(last_synced_at: str | None) -> bool:
    if not last_synced_at:
        return False
    try:
        ts = datetime.fromisoformat(last_synced_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts < timedelta(hours=CATALOG_SYNC_TTL_HOURS)
    except (ValueError, TypeError):
        return False


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
            published_at        = excluded.published_at,
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
                "INSERT INTO catalog_new_reports (ticker, report_form, period_type, year, quarter, title) VALUES (?,?,?,?,?,?)",
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


# ---------------------------------------------------------------------------
# Sync — one company
# ---------------------------------------------------------------------------

# Legal-form tokens that openinfo's /reports/main/ search does NOT match well
# when appended to the brand name (e.g. '"Aloqabank" ATB' → 0 hits, but
# 'Aloqabank' → 54 hits). Stripping them is what lets org_type (and therefore
# the NSBU Excel export URL) resolve for banks/insurers/JSCs.
_LEGAL_FORM_TOKENS = {
    "atb", "aj", "ak", "ato", "mchj", "qmj", "xk", "uk", "ooo", "aytb",
    "ао", "оао", "зао", "акб", "хк", "ук", "чп", "ип", "atb.", "aj.",
}


def _org_search_terms(company_name: str) -> list[str]:
    """Best-first candidate queries for openinfo's /reports/main/ search.

    openinfo's search engine fails on the full legal name (quotes + legal-form
    suffix), so we also try the de-quoted name and the bare brand token(s).
    """
    name = (company_name or "").strip()
    terms: list[str] = []
    if name:
        terms.append(name)
    cleaned = re.sub(r"""["«»“”'`]""", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned not in terms:
        terms.append(cleaned)
    tokens = [t for t in cleaned.split(" ") if t]
    brand = [t for t in tokens if t.lower().strip(".") not in _LEGAL_FORM_TOKENS]
    phrase = " ".join(brand).strip()
    if phrase and phrase not in terms:
        terms.append(phrase)
    if brand and brand[0] not in terms:
        terms.append(brand[0])
    return terms


def _fetch_main_results(session: Any, company_name: str, org_id: Any) -> tuple[list[dict], str | None]:
    """Return (org-filtered /reports/main/ records, org_type) for a company.

    Tries progressively cleaner search terms until one returns records for this
    org_id — openinfo's search misses the full legal name for many issuers.
    """
    for query in _org_search_terms(company_name):
        try:
            payload = _json_get(session, "/reports/main/", {"page": 1, "page_size": 200, "search": query})
        except Exception:
            continue
        results = list(payload.get("results") or []) if isinstance(payload, dict) else []
        filtered = [r for r in results if str(r.get("organization")) == str(org_id)]
        if filtered:
            org_type = next(
                ((r.get("properties") or {}).get("org_type") for r in filtered if (r.get("properties") or {}).get("org_type")),
                None,
            )
            return filtered, org_type
    return [], None


def _nsbu_export_urls(report_id: Any, period_type: str, org_type: str | None,
                      pdf_id: Any = None) -> tuple[str | None, str | None]:
    """Build (pdf_url, excel_url) for an NSBU accounting-report from its ids.

    NSBU records come from the ``/reports/accounting-report/`` endpoint, whose
    shape carries the financial line-items but no document URLs. The Excel export
    takes this record's own id (plus the period type and the issuer's
    ``org_type`` — without a correct org_type it returns HTTP 400, so excel_url
    is omitted when org_type is unknown).

    The PDF endpoint ``/ru/reports/to_pdf<id>/`` lives in a DIFFERENT id space:
    it takes the unified-feed record id, not this one. Passing the accounting id
    there serves whatever OTHER issuer's filing happens to sit at that feed id —
    measured 2026-08-09: UZML's annual 6021 rendered a cotton gin's quarterly.
    So the PDF link is built only from an explicitly supplied ``pdf_id`` (see
    ``_unified_pdf_id_map``); with none, no link is better than a wrong one.
    """
    if not report_id:
        return None, None
    pdf_url = f"{OPENINFO_WEB_BASE}/ru/reports/to_pdf{pdf_id}/" if pdf_id else None
    excel_url = None
    if org_type:
        excel_url = f"{OPENINFO_API_BASE}/reports/export-excel/?" + urlencode(
            {"report_type": period_type, "org_type": org_type, "report_id": report_id, "lang": "ru"}
        )
    return pdf_url, excel_url


def _unified_pdf_id_map(session: Any, org_id: Any) -> dict[str, int]:
    """Accounting object id → unified-feed record id, for one issuer.

    The unified feed is the only place the two id spaces meet: each record
    carries its own id (the ``to_pdf`` namespace) and a ``report_link`` whose
    tail is the accounting-report object id the structured sync works with.
    """
    out: dict[str, int] = {}
    if not org_id:
        return out
    for page in range(1, 6):
        try:
            payload = _json_get(session, "/reports/unified-financial-reports/",
                                {"format": "json", "page": page, "page_size": 200,
                                 "organization": org_id})
        except Exception:
            break
        results = list(payload.get("results") or []) if isinstance(payload, dict) else []
        for rec in results:
            m = re.search(r"/reports/[a-z]+/[a-z]+/(\d+)/?$", str(rec.get("report_link") or ""))
            if m and rec.get("id"):
                out[m.group(1)] = rec["id"]
        if len(results) < 200 or not (isinstance(payload, dict) and payload.get("next")):
            break
    return out


_ORG_TYPE_CANDIDATES = ("jsc", "bank", "insurance", "microfinance")


def _probe_org_type(session: Any, form2_records: list[dict], period_type: str) -> str | None:
    """Discover an issuer's org_type by probing the Excel export endpoint.

    openinfo's /reports/main/ search misses some issuers outright — names that
    tokenize to a single useless letter (e.g. "O'zqishloqelektrqurilish" → "O")
    return no org-matched records, so _fetch_main_results yields org_type=None and
    no NSBU Excel URL can be built (financials then stay empty). The export itself
    works once the right org_type label is supplied, so we try each candidate
    against a real report id and keep the first that returns a genuine .xlsx
    (HTTP 200 + spreadsheet content-type; a wrong org_type returns HTTP 400).
    """
    report_id = next(
        (doc.get("id") for rec in form2_records if (doc := _build_report_document(rec)).get("id")),
        None,
    )
    if not report_id:
        return None
    for org_type in _ORG_TYPE_CANDIDATES:
        url = _nsbu_export_urls(report_id, period_type, org_type)[1]
        try:
            resp = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)
            ctype = (resp.headers.get("content-type") or "").lower()
            resp.close()
        except Exception:  # noqa: BLE001 — any transport error just means "try next"
            continue
        if resp.status_code == 200 and ("spreadsheet" in ctype or "officedocument" in ctype):
            return org_type
    return None


def sync_company(
    ticker: str,
    company_name: str,
    *,
    force: bool = False,
    org_id: str | None = None,
) -> dict[str, Any]:
    conn = get_catalog_conn()

    # Check freshness unless forced
    if not force:
        row = conn.execute(
            "SELECT last_synced_at FROM catalog_companies WHERE ticker = ?", (ticker,)
        ).fetchone()
        if row and _is_fresh(row["last_synced_at"]):
            conn.close()
            return {"ticker": ticker, "skipped": True}

    session = _make_session()
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
            company = resolve_company(company_name, session=session)
            org_id = company.get("org_id")
            resolved_name = company.get("company_name") or company_name
        # Preferred share tickers (e.g. AGBAP) share the same org as the base ticker (AGBA).
        # If resolution failed, retry with the base ticker's company name.
        if not org_id and ticker.endswith("P"):
            base_name = _TICKER_TO_NAME.get(ticker[:-1])
            if base_name and base_name != company_name:
                company = resolve_company(base_name, session=session)
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
        logger.warning(
            "%s: issuer org changed %s -> %s; purging previously stored data",
            ticker, prev["org_id"], org_id,
        )
        with conn:
            _purge_ticker_data(conn, ticker)

    base = f"/reports/accounting-report/{org_id}/"

    # Fetch the /reports/main/ listing up front: it supplies the issuer's
    # org_type (needed to build NSBU Excel export URLs) and the MSFO/Audition
    # records consumed further below. openinfo's search misses the full legal
    # name for many issuers, so _fetch_main_results retries with cleaner terms.
    try:
        main_results, org_type = _fetch_main_results(session, company_name, org_id)
    except Exception as exc:
        main_results, org_type = [], None
        errors.append(f"reports/main: {exc}")

    # ---- NSBU annual -------------------------------------------------------
    try:
        form2_annual = _json_get(session, base, {"accounting_type": "form2", "report_type": "annual"})
        if not isinstance(form2_annual, list):
            form2_annual = []
    except Exception as exc:
        form2_annual = []
        errors.append(f"NSBU annual form2: {exc}")

    try:
        form1_annual = _json_get(session, base, {"accounting_type": "form1", "report_type": "annual"})
        if not isinstance(form1_annual, list):
            form1_annual = []
    except Exception as exc:
        form1_annual = []
        errors.append(f"NSBU annual form1: {exc}")

    # Index form1 by reporting_year for quick lookup
    form1_annual_by_year: dict[int, dict] = {}
    for rec in form1_annual:
        yr = rec.get("reporting_year")
        if isinstance(yr, int):
            doc = _build_report_document(rec)
            form1_annual_by_year[yr] = doc

    # The /reports/main/ search couldn't resolve org_type for this issuer, so the
    # NSBU Excel URLs below would all come out empty (→ no financials). Recover it
    # by probing the export endpoint against a real report id.
    if org_type is None and form2_annual:
        org_type = _probe_org_type(session, form2_annual, "annual")

    # The to_pdf id space (see _nsbu_export_urls). Stored NSBU pdf links are
    # cleared first: every one written before this map existed points at some
    # other issuer's document, and _upsert_report COALESCEs a NULL pdf_url with
    # the stored one — the wrong links would survive every re-sync otherwise.
    pdf_ids = _unified_pdf_id_map(session, org_id)
    with conn:
        conn.execute("UPDATE catalog_reports SET pdf_url = NULL "
                     "WHERE ticker = ? AND report_form = 'NSBU'", (ticker,))

    with conn:
        for rec in form2_annual:
            yr = rec.get("reporting_year")
            if not isinstance(yr, int):
                continue
            if _is_premature_annual_year(yr):
                # openinfo lists a placeholder "annual" for the in-progress fiscal
                # year (e.g. FY2026 mid-2026) whose export is a duplicate of, or an
                # incomplete stand-in for, the prior year. Ingesting it as the newest
                # annual dates the headline figures a year forward — skip it.
                continue
            doc2 = _build_report_document(rec)
            doc1 = form1_annual_by_year.get(yr)
            pdf_url, excel_url = _nsbu_export_urls(
                doc2.get("id"), "annual", org_type,
                pdf_id=pdf_ids.get(str(doc2.get("id") or "")))
            excel_url_form1 = _nsbu_export_urls(doc1.get("id"), "annual", org_type)[1] if doc1 else None
            new = _upsert_report(
                conn, ticker,
                report_form="NSBU",
                period_type="annual",
                year=yr,
                quarter=0,
                title=doc2.get("title"),
                published_at=doc2.get("published_at"),
                pdf_url=pdf_url,
                excel_url=excel_url,
                excel_url_form1=excel_url_form1,
                openinfo_report_id=str(doc2.get("id") or ""),
                object_id=str(doc2.get("object_id") or ""),
            )
            if new:
                added += 1

    # ---- NSBU quarterly ----------------------------------------------------
    try:
        form2_quarter = _json_get(session, base, {"accounting_type": "form2", "report_type": "quarter"})
        if not isinstance(form2_quarter, list):
            form2_quarter = []
    except Exception as exc:
        form2_quarter = []
        errors.append(f"NSBU quarter form2: {exc}")

    try:
        form1_quarter = _json_get(session, base, {"accounting_type": "form1", "report_type": "quarter"})
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
        q = _extract_quarter(period_str)
        if isinstance(yr, int) and q:
            doc = _build_report_document(rec)
            form1_quarter_by_yq[(yr, q)] = doc

    # Fall back to a quarterly report id if the issuer files no annuals but the
    # org_type still hasn't been resolved.
    if org_type is None and form2_quarter:
        org_type = _probe_org_type(session, form2_quarter, "quarter")

    with conn:
        for rec in form2_quarter:
            period_str = str(rec.get("period") or "")
            yr = rec.get("reporting_year")
            q = _extract_quarter(period_str)
            if not isinstance(yr, int) or not q:
                continue
            doc2 = _build_report_document(rec)
            doc1 = form1_quarter_by_yq.get((yr, q))
            pdf_url, excel_url = _nsbu_export_urls(
                doc2.get("id"), "quarter", org_type,
                pdf_id=pdf_ids.get(str(doc2.get("id") or "")))
            excel_url_form1 = _nsbu_export_urls(doc1.get("id"), "quarter", org_type)[1] if doc1 else None
            new = _upsert_report(
                conn, ticker,
                report_form="NSBU",
                period_type="quarter",
                year=yr,
                quarter=q,
                title=doc2.get("title"),
                published_at=doc2.get("published_at"),
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
                doc = _build_report_document(rec)
                yr = _extract_year(rec)
                if not isinstance(yr, int):
                    continue
                pt = str(doc.get("period_type") or "annual").lower()
                if pt not in ("annual", "quarter"):
                    pt = "annual"
                q = 0
                if pt == "quarter":
                    props = rec.get("properties") or {}
                    q = _extract_quarter(str(props.get("report_title") or "")) or 0
                new = _upsert_report(
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
            doc = _build_report_document(rec)
            form = doc.get("report_form") or rec.get("report_type")
            if form not in ("MSFO", "Audition"):
                continue
            pt = str(doc.get("period_type") or "annual").lower()
            yr = _extract_year(rec)
            q = 0
            if pt == "quarter":
                props = rec.get("properties") or {}
                period_str = str(props.get("report_title") or "")
                q = _extract_quarter(period_str) or 0
            new = _upsert_report(
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


# ---------------------------------------------------------------------------
# Sync — audition reports (separate endpoint, no org_id filter supported)
# ---------------------------------------------------------------------------

def _sync_auditions(conn: sqlite3.Connection, session: Any) -> int:
    """Fetch all /reports/audition/ records and upsert for known org_ids."""
    from openinfo_collector import OPENINFO_WEB_BASE

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
            payload = _json_get(session, "/reports/audition/", {"page": page, "page_size": 200})
        except Exception as exc:
            logger.warning("audition page %d failed: %s", page, exc)
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
                elif rec.get("pub_date"):
                    try:
                        yr = int(str(rec["pub_date"])[:4]) - 1
                    except (TypeError, ValueError):
                        pass
                new = _upsert_report(
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


# ---------------------------------------------------------------------------
# Sync — all companies
# ---------------------------------------------------------------------------

# Resolution sources that identify the issuer exactly (override table or the
# ticker/ISIN→INN→org join). Only these may CORRECT a stored org_id; name-based
# matches remain fill-only so a fuzzy result can never displace a good mapping.
_DETERMINISTIC_RESOLVERS = {"override", "ticker", "isin", "base_ticker_index"}


def _purge_ticker_data(conn: sqlite3.Connection, ticker: str) -> None:
    """Remove a ticker's landed data (used when its issuer org mapping changes)."""
    for table in ("catalog_reports", "catalog_new_reports", "catalog_financials", "catalog_ratios"):
        conn.execute(f"DELETE FROM {table} WHERE ticker = ?", (ticker,))


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

    session = _make_session()
    recs = er.resolve_all(session=session)
    conn = get_catalog_conn()
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
                    logger.warning(
                        "%s: issuer org corrected %s -> %s (%s); purging stored data",
                        rec["ticker"], prev["org_id"], org_id, rec.get("resolved_by"),
                    )
                    _purge_ticker_data(conn, rec["ticker"])
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
    resolved = sum(1 for r in recs if r.get("org_id"))
    orgs = {r["org_id"] for r in recs if r.get("org_id")}
    return {"discovered": len(recs), "resolved": resolved, "distinct_orgs": len(orgs),
            "upserted": upserted, "corrected": corrected, "records": recs}


def sync_all(tickers: list[str] | None = None, *, force: bool = False) -> dict[str, Any]:
    with _SYNC_LOCK:
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
                logger.info("Discovery: %s", {k: disc[k] for k in ("discovered", "resolved", "distinct_orgs")})
            except Exception:
                logger.exception("Security discovery failed; falling back to COMPANY_CATALOG")
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
                targets = reps or list(_TICKER_TO_NAME.keys())
            else:
                targets = list(_TICKER_TO_NAME.keys())

        total = len(targets)
        synced = 0
        skipped = 0
        all_errors: list[dict] = []

        try:
            _conn = get_catalog_conn()
            _cleanup_old_notifications(_conn)
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
            if ticker.endswith("P") and ticker[:-1] in _TICKER_TO_NAME:
                skipped += 1
                continue
            name = disc_name.get(ticker) or _TICKER_TO_NAME.get(ticker, ticker)
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
            conn = get_catalog_conn()
            session = _make_session()
            audit_added = _sync_auditions(conn, session)
            conn.close()
            logger.info("Audition sync added %d records", audit_added)
        except Exception as exc:
            all_errors.append({"ticker": "_audition", "errors": [str(exc)]})

        # NSBU pdf links can only be rebuilt for issuers whose org resolves —
        # a ticker stuck without one keeps whatever is stored, and every link
        # stored before the feed-id map existed points at some OTHER issuer's
        # document (see _nsbu_export_urls). For those, no download button is
        # better than a wrong document; the link returns when resolution does.
        try:
            conn = get_catalog_conn()
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
                    logger.info("cleared %d NSBU pdf links for unresolved issuers", cur.rowcount)
            conn.close()
        except Exception:
            logger.exception("stale NSBU pdf-link cleanup failed")

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

    conn = get_catalog_conn()
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
        canonical = _canonical_ticker(r["ticker"] for r in group)
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
            logger.exception("filing-driven catalog sync failed for %s", canonical)
            result["errors"].append({"ticker": canonical, "errors": [str(exc)]})
    return result


def _hours_since(stamp: Any) -> float | None:
    """Hours since an ISO timestamp, or None if there isn't one to read."""
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


def get_state(key: str) -> str | None:
    conn = get_catalog_conn()
    try:
        row = conn.execute("SELECT value FROM catalog_state WHERE key = ?", (key,)).fetchone()
    except Exception:  # noqa: BLE001 — a deployment that has not migrated yet
        return None
    finally:
        conn.close()
    return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    conn = get_catalog_conn()
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
    return _hours_since(get_state(FULL_SWEEP_KEY))


def _sweep_representatives() -> list[dict[str, Any]]:
    """One entry per issuer, under the ticker its catalog entry is listed by."""
    conn = get_catalog_conn()
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
        canonical = _canonical_ticker(m["ticker"] for m in members)
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
        if (_hours_since(r["last_synced_at"]) or float("inf")) >= older_than_hours
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
            logger.exception("stale catalog sync failed for %s", ticker)
            result["errors"].append({"ticker": ticker, "errors": [str(exc)]})
    result["remaining"] = max(0, len(stale) - len(result["targets"]))
    return result


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

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
    return (row["report_form"], row["period_type"], row["year"], row["quarter"])


def get_company_index(ticker: str) -> dict[str, Any]:
    conn = get_catalog_conn()
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
        SELECT report_form, period_type, year, quarter, pdf_url, excel_url, excel_url_form1
        FROM catalog_reports
        WHERE ticker IN ({placeholders})
        ORDER BY year DESC, quarter DESC
        """,
        siblings,
    ).fetchall()
    conn.close()

    # The same filing can be stored under two of the issuer's tickers; keep the
    # copy that carries the most download links.
    best: dict[tuple, Any] = {}
    for r in rows:
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
            "has_pdf": bool(r["pdf_url"]),
            "has_excel": bool(r["excel_url"]),
            "has_excel_form1": bool(r["excel_url_form1"]),
            "pdf_url": r["pdf_url"],
            "excel_url": r["excel_url"],
            "excel_url_form1": r["excel_url_form1"],
        }
        bucket = availability.setdefault(form, {"annual": [], "quarter": []})
        bucket.setdefault(pt, []).append(entry)

    return {
        "ticker": ticker,
        "company_name": company_row["company_name"] if company_row else _TICKER_TO_NAME.get(ticker, ticker),
        "sector": COMPANY_SECTORS.get(ticker),
        "org_id": company_row["org_id"] if company_row else None,
        "last_synced_at": company_row["last_synced_at"] if company_row else None,
        # Every ticker of this issuer — the entry stands for all of them.
        "tickers": siblings,
        "availability": availability,
        "years": sorted(years_seen, reverse=True),
        "report_count": len(reports),
    }


def get_report_urls(ticker: str, form: str, year: int, quarter: int) -> dict[str, Any] | None:
    conn = get_catalog_conn()
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
    conn = get_catalog_conn()
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
    conn = get_catalog_conn()
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


def upsert_ratio_cache(ticker: str, form: str, year: int, quarter: int, metrics: dict[str, Any]) -> None:
    conn = get_catalog_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO catalog_ratios
                (ticker, form, year, quarter, roa, roe, net_margin, debt_ratio, debt_to_equity, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET
                roa=excluded.roa, roe=excluded.roe, net_margin=excluded.net_margin,
                debt_ratio=excluded.debt_ratio, debt_to_equity=excluded.debt_to_equity,
                updated_at=datetime('now')
            """,
            (ticker, form, year, quarter,
             metrics.get("ROA"), metrics.get("ROE"), metrics.get("net_margin"),
             metrics.get("debt_ratio"), metrics.get("debt_to_equity")),
        )
    conn.close()


_FINANCIAL_KEYS = ("revenue", "gross_profit", "cash", "total_liabilities",
                   "net_income", "operating_income")


def upsert_financials_cache(ticker: str, form: str, year: int, quarter: int,
                            values: dict[str, Any], report_id: int | None = None) -> None:
    """Store the six NSBU headline indicators for a ticker/period.

    Every value here is parsed from the (year, quarter) statement itself, so the
    row's ``field_periods`` is cleared: any stale provenance from a previous
    enrichment no longer describes what is stored.

    A period that has not ended yet is refused here as it is on the push path —
    every writer into this table applies the same rule, or the one that does not
    becomes the way a fabricated period gets in.
    """
    if _is_future_period(year, quarter):
        logger.warning("financials: rejected %s %s Q%s — period has not ended", ticker, year, quarter)
        return
    conn = get_catalog_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO catalog_financials
                (ticker, form, year, quarter, revenue, gross_profit, cash,
                 total_liabilities, net_income, operating_income,
                 field_periods, report_id, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET
                revenue=excluded.revenue, gross_profit=excluded.gross_profit,
                cash=excluded.cash, total_liabilities=excluded.total_liabilities,
                net_income=excluded.net_income, operating_income=excluded.operating_income,
                field_periods=excluded.field_periods,
                -- A re-parse that cannot name its source must not erase the
                -- link the previous one established.
                report_id=COALESCE(excluded.report_id, catalog_financials.report_id),
                updated_at=datetime('now')
            """,
            (ticker, form, year, quarter,
             values.get("revenue"), values.get("gross_profit"), values.get("cash"),
             values.get("total_liabilities"), values.get("net_income"),
             values.get("operating_income"),
             _encode_field_periods(values.get("field_periods")), report_id),
        )
    conn.close()


# Snapshot committed to the repo, generated where openinfo.uz is reachable. Lets
# environments that can't reach openinfo (e.g. a datacenter IP openinfo blocks)
# still serve financials instead of empty "—" columns.
_FINANCIALS_SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "financials_seed.json")
_seed_lock = threading.Lock()
_seeded = False


def _maybe_seed_financials(conn: sqlite3.Connection, form: str = "NSBU") -> None:
    """Bootstrap catalog_financials from the bundled snapshot when it's empty.

    Only fills when no rows exist for the form — never overwrites values produced
    by a live sync. Guarded so it runs at most once per process.
    """
    global _seeded
    if _seeded:
        return
    with _seed_lock:
        if _seeded:
            return
        try:
            n = conn.execute("SELECT COUNT(*) FROM catalog_financials WHERE form=?", (form,)).fetchone()[0]
            if not n and os.path.exists(_FINANCIALS_SEED_PATH):
                with open(_FINANCIALS_SEED_PATH, encoding="utf-8") as f:
                    rows = (json.load(f) or {}).get("rows") or []
                with conn:
                    for r in rows:
                        conn.execute(
                            """
                            INSERT INTO catalog_financials
                                (ticker, form, year, quarter, revenue, gross_profit, cash,
                                 total_liabilities, net_income, operating_income, updated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
                            ON CONFLICT DO NOTHING
                            """,
                            (r.get("ticker"), r.get("form") or form, r.get("year") or 0,
                             r.get("quarter") or 0, r.get("revenue"), r.get("gross_profit"),
                             r.get("cash"), r.get("total_liabilities"), r.get("net_income"),
                             r.get("operating_income")),
                        )
                logger.info("Seeded catalog_financials from snapshot: %d rows", len(rows))
        except Exception:
            logger.exception("financials seed failed")
        finally:
            _seeded = True


def _financials_num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _financials_period(row: dict) -> tuple[int, int] | None:
    """(year, quarter) for an incoming row, or None if it must not be stored.

    Rejects periods that have not ended yet. This is the входная проверка the
    "2026 Q4" rows needed: QZSM and UQEQ reached the served cache labelled with a
    quarter of the current year that is still months away, because openinfo signed
    their annual reports with a future year-end and nothing downstream questioned
    it. A period is a claim about a closed accounting interval — if the interval
    is open, the row is not a report and is dropped rather than re-dated.
    """
    try:
        year = int(row.get("year") or 0)
        quarter = int(row.get("quarter") or 0)
    except (TypeError, ValueError):
        return None
    if _is_future_period(year, quarter):
        logger.warning("financials: rejected %s %s Q%s — period has not ended",
                       row.get("ticker"), year, quarter)
        return None
    return year, quarter


def bulk_upsert_financials(rows: list[dict], form: str = "NSBU") -> int:
    """Overwrite the financials cache from an externally-computed batch.

    Used by the admin push endpoint so a collector running where openinfo IS
    reachable can refresh prod (whose datacenter IP openinfo blocks). Unlike the
    seed loader, this overwrites existing values (ON CONFLICT DO UPDATE).
    """
    _num = _financials_num

    conn = get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                ticker = str(r.get("ticker") or "").strip().upper()
                if not ticker:
                    continue
                period = _financials_period(r)
                if period is None:
                    continue
                year, quarter = period
                conn.execute(
                    """
                    INSERT INTO catalog_financials
                        (ticker, form, year, quarter, revenue, gross_profit, cash,
                         total_liabilities, net_income, operating_income,
                         noninterest_income, org_type, balance_period,
                         field_periods, prior_period, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET
                        revenue=excluded.revenue, gross_profit=excluded.gross_profit,
                        cash=excluded.cash, total_liabilities=excluded.total_liabilities,
                        net_income=excluded.net_income, operating_income=excluded.operating_income,
                        noninterest_income=excluded.noninterest_income,
                        -- An upsert that says nothing about the form or the
                        -- balance must not erase what a reconcile established.
                        org_type=COALESCE(excluded.org_type, catalog_financials.org_type),
                        balance_period=COALESCE(excluded.balance_period,
                                                catalog_financials.balance_period),
                        field_periods=excluded.field_periods,
                        prior_period=excluded.prior_period,
                        updated_at=datetime('now')
                    """,
                    (ticker, str(r.get("form") or form), year, quarter,
                     _num(r.get("revenue")), _num(r.get("gross_profit")), _num(r.get("cash")),
                     _num(r.get("total_liabilities")), _num(r.get("net_income")),
                     _num(r.get("operating_income")),
                     _num(r.get("noninterest_income")),
                     (str(r.get("org_type")) if r.get("org_type") else None),
                     _encode_balance_period(r.get("balance")),
                     _encode_field_periods(r.get("field_periods")),
                     _encode_prior_period(r.get("prior"))),
                )
                n += 1
    finally:
        conn.close()
    return n


def bulk_replace_financials(rows: list[dict], form: str = "NSBU") -> int:
    """Make the supplied rows the *authoritative* set of periods for their tickers.

    Unlike :func:`bulk_upsert_financials` (which only upserts one (ticker, form,
    year, quarter) key and leaves other period rows in place), this deletes every
    stored period for each ticker in ``rows`` and inserts what was supplied. It is
    used to push structured-JSON reconciled figures (openinfo_reconcile): the read
    path serves the highest-ranked period, so a stale or spurious higher period
    already in the cache would otherwise shadow a correct annual/earlier period.

    A ticker may legitimately supply SEVERAL periods — the latest cumulative
    quarter plus the last complete fiscal year that ratios need a 12-month
    denominator from — so the delete happens once per ticker, before any insert.
    Deleting per row instead (as this did while every ticker had exactly one row)
    silently keeps only whichever period happens to be pushed last. Values are
    stored in thousands of UZS, as everywhere in this cache.
    """
    _num = _financials_num

    # A replace push speaks for a ticker's LATEST periods — the newest cumulative
    # quarter plus its companion fiscal year — and its job is to clear a stale or
    # spurious period that would SHADOW them (the read path serves the
    # highest-ranked period). Deleting the whole ticker did far more than that:
    # every backfilled historical year went with it, so the multi-year income
    # statement landed on 2026-08-08 and was gone by the next daily reconcile,
    # with the hourly filings watch erasing it ticker by ticker in between.
    # Nothing ranked BELOW the push can shadow it, so only the range from the
    # push's oldest period upward is cleared; the history behind it stands.
    def _floor(year: int, quarter: int) -> int:
        # Stored rows rank as in get_company_ratios_cached: an annual (quarter 0)
        # is the year's FINAL figure, year*10+5. A pushed annual clears from the
        # START of its year — its own stale quarters are partials it supersedes —
        # while a pushed quarter clears only from itself upward.
        return year * 10 + (0 if not quarter else int(quarter))

    floors: dict[tuple[str, str], int] = {}
    for r in rows or []:
        ticker = str(r.get("ticker") or "").strip().upper()
        period = _financials_period(r)
        if not ticker or period is None:
            continue
        key = (ticker, str(r.get("form") or form))
        rank = _floor(*period)
        floors[key] = min(floors.get(key, rank), rank)

    conn = get_catalog_conn()
    n = 0
    cleared: set[tuple[str, str]] = set()
    try:
        with conn:
            for r in rows or []:
                ticker = str(r.get("ticker") or "").strip().upper()
                if not ticker:
                    continue
                period = _financials_period(r)
                if period is None:
                    continue
                year, quarter = period
                row_form = str(r.get("form") or form)
                if (ticker, row_form) not in cleared:
                    conn.execute(
                        "DELETE FROM catalog_financials WHERE ticker=? AND form=? "
                        "AND (year*10 + CASE WHEN quarter=0 THEN 5 ELSE quarter END) >= ?",
                        (ticker, row_form, floors[(ticker, row_form)]))
                    cleared.add((ticker, row_form))
                conn.execute(
                    """
                    -- ON CONFLICT rather than INSERT OR REPLACE: the SQLite
                    -- form deletes the old row and inserts a new one, which
                    -- drops any column this statement does not name, and it
                    -- exists in no other dialect.
                    INSERT INTO catalog_financials
                        (ticker, form, year, quarter, revenue, gross_profit, cash,
                         total_liabilities, net_income, operating_income,
                         noninterest_income, org_type, balance_period,
                         field_periods, prior_period, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET
                        revenue=excluded.revenue, gross_profit=excluded.gross_profit,
                        cash=excluded.cash, total_liabilities=excluded.total_liabilities,
                        net_income=excluded.net_income,
                        operating_income=excluded.operating_income,
                        noninterest_income=excluded.noninterest_income,
                        org_type=excluded.org_type,
                        balance_period=excluded.balance_period,
                        field_periods=excluded.field_periods,
                        prior_period=excluded.prior_period,
                        updated_at=excluded.updated_at
                    """,
                    (ticker, row_form, year, quarter,
                     _num(r.get("revenue")), _num(r.get("gross_profit")), _num(r.get("cash")),
                     _num(r.get("total_liabilities")), _num(r.get("net_income")),
                     _num(r.get("operating_income")),
                     _num(r.get("noninterest_income")),
                     (str(r.get("org_type")) if r.get("org_type") else None),
                     _encode_balance_period(r.get("balance")),
                     _encode_field_periods(r.get("field_periods")),
                     _encode_prior_period(r.get("prior"))),
                )
                n += 1
    finally:
        conn.close()
    return n


_TRADE_STAT_KEYS = ("total_value", "total_qty", "trade_count", "avg_price",
                    "largest_qty", "largest_value", "largest_pct_value", "largest_pct_qty")


def bulk_upsert_trade_stats(rows: list[dict], trade_date: str | None = None) -> int:
    """Overwrite the latest-day per-ISIN trade statistics cache.

    A security's stats only ever move FORWARD in time: the backfill path derives
    a security's "last trading day" from the board, and a board row that lags (or
    an openinfo archive that answers for the wrong day) would otherwise replace a
    fresh session with an older one, leaving turnover that belongs to no quote on
    the page. Rows dated before what is already stored are skipped, not written.
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    conn = get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                isin = str(r.get("isin") or "").strip().upper()
                if not isin:
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO catalog_trade_stats
                        (isin, trade_date, total_value, total_qty, trade_count, avg_price,
                         largest_qty, largest_value, largest_pct_value, largest_pct_qty,
                         open_price, high_price, low_price, close_price, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(isin) DO UPDATE SET
                        trade_date=excluded.trade_date, total_value=excluded.total_value,
                        total_qty=excluded.total_qty, trade_count=excluded.trade_count,
                        avg_price=excluded.avg_price, largest_qty=excluded.largest_qty,
                        largest_value=excluded.largest_value,
                        largest_pct_value=excluded.largest_pct_value,
                        largest_pct_qty=excluded.largest_pct_qty,
                        open_price=excluded.open_price, high_price=excluded.high_price,
                        low_price=excluded.low_price, close_price=excluded.close_price,
                        updated_at=datetime('now')
                    WHERE excluded.trade_date >= catalog_trade_stats.trade_date
                    """,
                    (isin, str(r.get("trade_date") or trade_date or ""),
                     _num(r.get("total_value")), _num(r.get("total_qty")),
                     int(_num(r.get("trade_count")) or 0), _num(r.get("avg_price")),
                     _num(r.get("largest_qty")), _num(r.get("largest_value")),
                     _num(r.get("largest_pct_value")), _num(r.get("largest_pct_qty")),
                     _num(r.get("open_price")), _num(r.get("high_price")),
                     _num(r.get("low_price")), _num(r.get("close_price"))),
                )
                n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    finally:
        conn.close()
    return n


def get_all_trade_stats() -> dict[str, dict[str, Any]]:
    """Return the cached latest-day trade statistics per ISIN: {isin: {...}}."""
    conn = get_catalog_conn()
    rows = conn.execute(
        """SELECT isin, trade_date, total_value, total_qty, trade_count, avg_price,
                  largest_qty, largest_value, largest_pct_value, largest_pct_qty,
                  open_price, high_price, low_price, close_price, updated_at
           FROM catalog_trade_stats"""
    ).fetchall()
    conn.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        # VWAP on read (ТЗ §3.4/§3.8): volume-weighted price = turnover / quantity.
        tv, tq = d.get("total_value"), d.get("total_qty")
        d["vwap"] = round(tv / tq, 2) if (tv and tq) else None
        out[r["isin"]] = d
    return out


_QUOTE_COLS = (
    "ticker", "name", "market", "share_type", "trade_date", "close_price", "prev_close",
    "prev_close_date", "change_value", "change_percent", "open_price", "high_price",
    "low_price", "quantity", "turnover", "shares_outstanding", "market_cap",
)


def bulk_upsert_quotes(rows: list[dict]) -> int:
    """Store the exchange's session quotes, newest session wins.

    Forward-only, for the same reason ``bulk_upsert_trade_stats`` is: a quote is
    written only for a session the security actually traded in, and a re-read of
    an older page (or a run that starts before the day's first execution) must
    never replace a fresh session with a stale one.

    A LATER session replaces the row outright. The SAME session may only add to
    it: the exchange publishes a finished session's close, change, quantity and
    turnover in its daily history, but not that session's open/high/low, so the
    morning run that settles yesterday's numbers carries no OHLC — and writing
    those NULLs over the columns the 16:10 run captured would lose them to a
    read that knew strictly less.
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    numeric = {"close_price", "prev_close", "change_value", "change_percent", "open_price",
               "high_price", "low_price", "quantity", "turnover", "shares_outstanding",
               "market_cap"}
    assignments = ", ".join(
        f"{c}=CASE WHEN excluded.trade_date > catalog_quotes.trade_date "
        f"THEN excluded.{c} ELSE COALESCE(excluded.{c}, catalog_quotes.{c}) END"
        for c in _QUOTE_COLS)
    conn = get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                isin = str(r.get("isin") or "").strip().upper()
                day = str(r.get("trade_date") or "").strip()
                if not isin or not day:
                    continue
                values = [_num(r.get(c)) if c in numeric else (r.get(c) or None)
                          for c in _QUOTE_COLS]
                cur = conn.execute(
                    f"""
                    INSERT INTO catalog_quotes (isin, {', '.join(_QUOTE_COLS)}, updated_at)
                    VALUES ({','.join('?' * (len(_QUOTE_COLS) + 1))}, datetime('now'))
                    ON CONFLICT(isin) DO UPDATE SET {assignments}, updated_at=datetime('now')
                    WHERE excluded.trade_date >= catalog_quotes.trade_date
                    """,
                    [isin, *values],
                )
                n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    finally:
        conn.close()
    return n


_QUOTE_HISTORY_COLS = ("close_price", "change_value", "quantity", "turnover")


def bulk_upsert_quote_history(rows: list[dict]) -> int:
    """Store settled daily closes, one statement per batch.

    Row-at-a-time is what took the catalog register to a 120-second timeout on
    Postgres (7670 statements for 7670 rows). This writes ~2300 rows — every
    security's last ~21 sessions — on every collector run, so it batches or it
    does not ship: one executemany, and the round trip is the cost, not the row.

    The batch is deduplicated on (isin, trade_date) first. PostgreSQL refuses an
    ON CONFLICT that would touch the same key twice in one statement, and the
    same session legitimately arrives twice in a run — a security read once for
    its live quote and again for a settled row lands both.

    Last write wins on a repeated session, deliberately. A row read mid-session
    is provisional and a later read of the same day is strictly more settled;
    past sessions are immutable in the source, so for them the update is a
    no-op writing identical values.
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    def _day(v: Any) -> str | None:
        """YYYYMMDD, the form the catalog stores.

        Two sources feed this table and they disagree: the exchange page's daily
        history is already YYYYMMDD, openinfo's conclusions archive is ISO. Both
        sort correctly on their own and neither sorts against the other, so the
        normalisation happens here rather than at each call site — a series half
        in one form would order by its leading digits and draw a scrambled line.
        """
        s = str(v or "").strip()
        if re.fullmatch(r"\d{8}", s):
            return s
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"
        m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s)
        return f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else None

    seen: dict[tuple[str, str], list[Any]] = {}
    for r in rows or []:
        isin = str(r.get("isin") or "").strip().upper()
        day = _day(r.get("trade_date") or r.get("date"))
        if not isin or not day:
            continue
        seen[(isin, day)] = [isin, day, _num(r.get("close_price") if r.get("close_price") is not None
                                            else r.get("close")),
                             _num(r.get("change_value") if r.get("change_value") is not None
                                  else r.get("change")),
                             _num(r.get("quantity")), _num(r.get("turnover"))]
    if not seen:
        return 0
    assignments = ", ".join(f"{c}=excluded.{c}" for c in _QUOTE_HISTORY_COLS)
    conn = get_catalog_conn()
    try:
        with conn:
            conn.executemany(
                f"""
                INSERT INTO catalog_quote_history
                    (isin, trade_date, {', '.join(_QUOTE_HISTORY_COLS)}, updated_at)
                VALUES ({','.join('?' * (len(_QUOTE_HISTORY_COLS) + 2))}, datetime('now'))
                ON CONFLICT(isin, trade_date) DO UPDATE SET
                    {assignments}, updated_at=datetime('now')
                """,
                list(seen.values()),
            )
    finally:
        conn.close()
    return len(seen)


def get_quote_history(isins: Sequence[str], days: int = 30) -> dict[str, list[dict[str, Any]]]:
    """Recent settled closes for several securities, oldest first, keyed by ISIN.

    One query for the whole set — the point of storing this at all was to stop
    a list of securities costing one upstream request per row.
    """
    codes = [str(i).strip().upper() for i in (isins or []) if str(i or "").strip()]
    if not codes:
        return {}
    days = max(1, min(int(days or 30), 3650))
    placeholders = ",".join("?" * len(codes))
    conn = get_catalog_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT isin, trade_date, close_price, change_value, quantity, turnover
            FROM catalog_quote_history
            WHERE isin IN ({placeholders})
            ORDER BY isin, trade_date
            """,
            codes,
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r["isin"], []).append(dict(r))
    # The window is the last N SESSIONS the security has, not the last N calendar
    # days: a quiet security would otherwise return an empty series and read as
    # "no data" when what it did was not trade.
    return {isin: series[-days:] for isin, series in out.items()}


def get_all_quotes() -> dict[str, dict[str, Any]]:
    """Every stored exchange quote, keyed by ISIN."""
    conn = get_catalog_conn()
    try:
        rows = conn.execute(
            f"SELECT isin, {', '.join(_QUOTE_COLS)}, updated_at FROM catalog_quotes"
        ).fetchall()
    finally:
        conn.close()
    return {r["isin"]: dict(r) for r in rows}


_LISTING_COLS = (
    "ticker", "isin", "name", "share_type", "listing_date", "shares_outstanding",
    "reference_price", "last_price", "last_trade_date", "open_price", "high_price",
    "low_price", "volume", "market_cap",
)


def bulk_upsert_listings(rows: list[dict]) -> int:
    """Overwrite the exchange-listing registry from an externally-computed batch.

    Pushed by the collector (where openinfo is reachable) so prod can show
    listed-but-inactive issuers on the market board even though they are missing
    from the live uzse-stock feed. Keyed by security ticker (ordinary + preferred
    lines are distinct rows, e.g. KSCM / KSCMP).
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None or v == "" else float(v)
        except (TypeError, ValueError):
            return None

    conn = get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                ticker = str(r.get("ticker") or "").strip().upper()
                if not ticker or ticker in DELISTED_TICKERS:
                    # Deleted from the site: an older collector build still emits
                    # these, and the upsert would silently resurrect them.
                    continue
                conn.execute(
                    """
                    INSERT INTO catalog_listings
                        (ticker, isin, name, share_type, listing_date, shares_outstanding,
                         reference_price, last_price, last_trade_date, open_price, high_price,
                         low_price, volume, market_cap, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(ticker) DO UPDATE SET
                        isin=excluded.isin, name=excluded.name, share_type=excluded.share_type,
                        listing_date=excluded.listing_date,
                        shares_outstanding=excluded.shares_outstanding,
                        reference_price=excluded.reference_price, last_price=excluded.last_price,
                        last_trade_date=excluded.last_trade_date, open_price=excluded.open_price,
                        high_price=excluded.high_price, low_price=excluded.low_price,
                        volume=excluded.volume, market_cap=excluded.market_cap,
                        updated_at=datetime('now')
                    """,
                    (ticker, str(r.get("isin") or "") or None, str(r.get("name") or "") or None,
                     str(r.get("share_type") or "") or None, str(r.get("listing_date") or "") or None,
                     _num(r.get("shares_outstanding")), _num(r.get("reference_price")),
                     _num(r.get("last_price")), str(r.get("last_trade_date") or "") or None,
                     _num(r.get("open_price")), _num(r.get("high_price")), _num(r.get("low_price")),
                     _num(r.get("volume")), _num(r.get("market_cap"))),
                )
                n += 1
    finally:
        conn.close()
    return n


def get_all_listings() -> dict[str, dict[str, Any]]:
    """Return the cached exchange-listing registry per ticker: {ticker: {...}}."""
    conn = get_catalog_conn()
    rows = conn.execute(
        f"SELECT {', '.join(_LISTING_COLS)}, updated_at FROM catalog_listings"
    ).fetchall()
    conn.close()
    return {r["ticker"]: dict(r) for r in rows
            if r["ticker"] not in DELISTED_TICKERS}


# Every catalog table that keys rows by ticker, so a purge leaves nothing behind:
# the registry row itself, the issuer record, its report history (which also feeds
# the market-events timeline), the derived numbers and the org_map facts.
_PURGE_TABLES = (
    ("catalog_listings", "ticker"),
    ("catalog_quotes", "ticker"),
    ("catalog_companies", "ticker"),
    ("catalog_reports", "ticker"),
    ("catalog_new_reports", "ticker"),
    ("catalog_ratios", "ticker"),
    ("catalog_financials", "ticker"),
    ("facts", "entity_id"),        # org_map rows are keyed by ticker, not org id
    ("news_entities", "ticker"),   # issuer tags on news stories (story itself stays)
)


def purge_delisted(tickers: set[str] | frozenset[str] | None = None) -> dict[str, int]:
    """Delete every trace of the delisted securities from the catalog DB.

    ``bulk_upsert_listings`` is upsert-only — it never drops rows the collector
    stopped emitting — so filtering the collector alone would leave these tickers
    in a persisted volume forever. This is the deletion half: idempotent, safe to
    run on every boot, and cheap when there is nothing left to remove. Returns
    ``{table: rows_deleted}`` for the tables that actually gave up rows.
    """
    targets = {t.upper() for t in (tickers if tickers is not None else DELISTED_TICKERS)}
    if not targets:
        return {}
    placeholders = ",".join("?" * len(targets))
    params = sorted(targets)
    deleted: dict[str, int] = {}
    conn = get_catalog_conn()
    try:
        # Through dbx, not by reading SQLite's own catalog table: that table does
        # not exist on Postgres, so since the cutover this raised before deleting
        # anything and the purge only ever *looked* done — the read filters were
        # hiding the very rows it had failed to remove.
        existing = set(dbx.tables(conn))
        with conn:
            # Trade stats are keyed by ISIN, so resolve them through the registry
            # rows before those rows are deleted and the link is lost.
            if {"catalog_listings", "catalog_trade_stats"} <= existing:
                isins = [r[0] for r in conn.execute(
                    f"SELECT isin FROM catalog_listings "
                    f"WHERE UPPER(ticker) IN ({placeholders}) AND isin IS NOT NULL AND isin != ''",
                    params)]
                if isins:
                    cur = conn.execute(
                        f"DELETE FROM catalog_trade_stats WHERE isin IN ({','.join('?' * len(isins))})",
                        isins)
                    if cur.rowcount > 0:
                        deleted["catalog_trade_stats"] = cur.rowcount
            for table, column in _PURGE_TABLES:
                if table not in existing:
                    continue
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE UPPER({column}) IN ({placeholders})", params)
                if cur.rowcount > 0:
                    deleted[table] = cur.rowcount
            # What a purge by ticker cannot reach. Both these tables are keyed by
            # ISIN, and the row holding both keys — the registry line — is the one
            # just deleted, so a quote for a security the mirror never named has
            # nothing left to resolve through. Left behind it survives every boot
            # and walks back onto the board without a ticker. Only for the standard
            # whole-set purge: a caller naming its own tickers gets exactly those.
            if tickers is None and DELISTED_ISINS:
                isins = sorted(DELISTED_ISINS)
                marks = ",".join("?" * len(isins))
                # The daily-close store is keyed by ISIN alone, so it outlives the
                # registry row too — a removed security's price series has no
                # reader left, but keeping it would mean the site still stores the
                # history of a company it no longer shows.
                for table in ("catalog_quotes", "catalog_trade_stats", "catalog_quote_history"):
                    if table not in existing:
                        continue
                    cur = conn.execute(
                        f"DELETE FROM {table} WHERE UPPER(isin) IN ({marks})", isins)
                    if cur.rowcount > 0:
                        deleted[table] = deleted.get(table, 0) + cur.rowcount
    finally:
        conn.close()
    if deleted:
        logger.info("purged delisted securities: %s", deleted)
    return deleted


def _decode_field_periods(raw: Any) -> dict[str, str]:
    """Parse the stored ``field_periods`` JSON, tolerating legacy NULL rows."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items() if v}


def _encode_field_periods(value: Any) -> str | None:
    """Serialize ``field_periods`` for storage; None when there is nothing to say."""
    decoded = _decode_field_periods(value)
    return json.dumps(decoded, ensure_ascii=False, sort_keys=True) if decoded else None


_PRIOR_KEYS = ("revenue", "gross_profit", "net_income", "operating_income")


def _decode_prior_period(raw: Any) -> dict[str, Any] | None:
    """Parse the stored comparative period, tolerating rows written before it."""
    if not raw:
        return None
    parsed = raw if isinstance(raw, dict) else None
    if parsed is None:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, dict) or parsed.get("year") is None:
        return None
    out: dict[str, Any] = {"year": int(parsed["year"]), "quarter": int(parsed.get("quarter") or 0)}
    out["is_ytd"] = bool(out["quarter"])
    out["period_months"] = _period_months(out["year"], out["quarter"])
    for key in _PRIOR_KEYS:
        out[key] = _financials_num(parsed.get(key))
    return out


def _encode_prior_period(value: Any) -> str | None:
    """Serialize the comparative period for storage; None when it says nothing."""
    if not isinstance(value, dict) or value.get("year") is None:
        return None
    payload = {"year": int(value["year"]), "quarter": int(value.get("quarter") or 0)}
    for key in _PRIOR_KEYS:
        payload[key] = _financials_num(value.get(key))
    if all(payload[key] is None for key in _PRIOR_KEYS):
        return None
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


_BALANCE_KEYS = ("equity_start", "equity_end", "assets_start", "assets_end")


def _decode_balance_period(raw: Any) -> dict[str, Any] | None:
    """Parse the stored filed-balance block, tolerating rows written before it."""
    if not raw:
        return None
    parsed = raw if isinstance(raw, dict) else None
    if parsed is None:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, dict):
        return None
    out = {key: _financials_num(parsed.get(key)) for key in _BALANCE_KEYS}
    return out if any(v is not None for v in out.values()) else None


def _encode_balance_period(value: Any) -> str | None:
    """Serialize the filed-balance block; None when it says nothing."""
    if not isinstance(value, dict):
        return None
    payload = {key: _financials_num(value.get(key)) for key in _BALANCE_KEYS}
    if all(v is None for v in payload.values()):
        return None
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _financials_enrich_enabled() -> bool:
    """Whether to apply org/fact enrichment when reading financials.

    Enrichment (fact-store corrections, cross-ticker inheritance) must run in the
    collector — where openinfo is reachable and the org mapping is fresh — before
    it pushes the final values. It must NOT run when serving on the deployment:
    prod's catalog_companies/org map is stale (openinfo is blocked there, so it
    never re-syncs), and re-enriching would re-inject a *different* entity's
    numbers over the clean pushed values (the org-1001 → OCBK/MNGM bug). Default
    off; the collector sets FINANCIALS_ENRICH_ON_READ=1.
    """
    return os.getenv("FINANCIALS_ENRICH_ON_READ", "0").strip().lower() in {"1", "true", "yes", "on"}


def get_all_financials(form: str = "NSBU") -> dict[str, dict[str, Any]]:
    """Return the most recent cached indicators per ticker: {ticker: {...}}.

    Picks the latest period (year, then quarter) available for each ticker. Org/
    fact enrichment runs only when ``_financials_enrich_enabled()`` (collector),
    so the deployment serves exactly what the collector pushed.
    """
    conn = get_catalog_conn()
    _maybe_seed_financials(conn, form)
    # Period ranking, in SQL, matching _period_key() exactly. Three things this
    # has to get right and the old `MAX(year * 10 + quarter)` did not:
    #
    #  1. An ANNUAL row is stored with quarter = 0, so it ranked BELOW every
    #     quarter of its own year — a completed FY2025 annual lost to 2025 Q1.
    #     _period_key ranks an annual as 5 (the complete, final figure for that
    #     year); the CASE below does the same, so the two orderings agree.
    #  2. A premature annual (fiscal year not yet ended) is openinfo's in-progress
    #     placeholder and must never win. Quarterly periods of the current year
    #     stay eligible — they are real point-in-time filings.
    #  3. A quarter outside 1-4 is a corrupt source period ('2025Q7'); at
    #     quarter = 7 it outranked every real period. Excluded outright.
    #  4. A period stamped beyond the current calendar year cannot be a filing
    #     that exists yet, quarterly or not. A single mis-stamped row (openinfo
    #     does mis-stamp period-ends) otherwise wins "latest" forever and shadows
    #     the issuer's real figures.
    last_fy = _latest_complete_fiscal_year()
    this_year = last_fy + 1
    period_rank = "(f.year * 10 + CASE WHEN f.quarter = 0 THEN 5 ELSE f.quarter END)"
    eligible = (
        "f.form = :form "
        "AND f.year IS NOT NULL "
        "AND f.quarter BETWEEN 0 AND 4 "
        "AND f.year <= :this_year "
        "AND NOT (f.quarter = 0 AND f.year > :last_fy)"
    )
    rows = conn.execute(
        f"""
        SELECT f.ticker, f.year, f.quarter, f.revenue, f.gross_profit, f.cash,
               f.total_liabilities, f.net_income, f.operating_income,
               f.noninterest_income, f.org_type, f.balance_period,
               f.field_periods, f.prior_period, f.report_id, f.updated_at
        FROM catalog_financials f
        JOIN (
            SELECT f.ticker AS ticker, MAX{period_rank} AS rank
            FROM catalog_financials f
            WHERE {eligible}
            GROUP BY f.ticker
        ) latest
          ON latest.ticker = f.ticker AND {period_rank} = latest.rank
        WHERE {eligible}
        """,
        {"form": form, "last_fy": last_fy, "this_year": this_year},
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r["ticker"]] = {
            "year": r["year"],
            "quarter": r["quarter"],
            # Quarterly NSBU flows are cumulative from Jan 1 — flag it so the
            # client can label a Q2 figure as "6 months" rather than pass a
            # part-year number off as a full-year one next to annual rows.
            "is_ytd": bool(r["quarter"]),
            "period_months": _period_months(r["year"], r["quarter"]),
            "revenue": r["revenue"],
            "gross_profit": r["gross_profit"],
            "cash": r["cash"],
            "total_liabilities": r["total_liabilities"],
            "net_income": r["net_income"],
            "operating_income": r["operating_income"],
            # Bank total income's second half; None on every other form.
            "noninterest_income": r["noninterest_income"],
            # The NSBU form the figures were read from (jsc/bank/insurance/
            # microfinance) — the display rules key off the form, not a guess.
            "org_type": r["org_type"],
            # The filed balance for THIS period: equity/assets at start and end,
            # the denominators P/B and averaged ROE/ROA are built from.
            "balance": _decode_balance_period(r["balance_period"]),
            # {field: period} for any value that does NOT belong to (year, quarter)
            # — a bank's revenue is only published as an annual indicator, so the
            # cell must say which period it describes rather than borrow the row's.
            "field_periods": _decode_field_periods(r["field_periods"]),
            # The comparative the SAME filing prints for the year before — P&L
            # only, labelled with its own period, so a year-on-year change is
            # struck against the issuer's own restated figure rather than against
            # a separately-filed report that may have been restated since.
            "prior": _decode_prior_period(r["prior_period"]),
            # The report this row was read from (ТЗ Дополнение 1 §Б.2). Every
            # figure carries its first source, so a disagreement about a number
            # is settled by opening the filing rather than by argument.
            "report_id": r["report_id"],
            "updated_at": r["updated_at"],
        }
    _attach_annual_companion(conn, out, form)
    if _financials_enrich_enabled():
        _inherit_financials_by_org(conn, out)
        _enrich_financials_from_facts(conn, out)
    conn.close()
    return out


def _attach_annual_companion(conn: sqlite3.Connection, out: dict[str, dict[str, Any]],
                             form: str) -> None:
    """Hang the last complete fiscal year off each row as ``annual``.

    The latest period is the freshest figure but usually a cumulative quarter, and
    every ratio built on a P&L line then divides by 3, 6 or 9 months of earnings
    while the issuer next to it divides by 12 — the same P/E column measuring
    different things. The companion is the comparable denominator: a real filed
    12-month period, not a quarter multiplied up. It is absent (None) when the row
    already IS an annual, and when no complete year has been collected.

    A Q4 quarterly stands in when no annual was ever filed: NSBU quarters are
    cumulative from 1 January, so a Q4 filing IS twelve months of activity with a
    31 December balance (ТЗ мультипликаторов: KSCM's newest annual is 2022 while
    its quarters are current). A real annual of the same year still outranks it —
    the audited annual is the year's final word.
    """
    last_fy = _latest_complete_fiscal_year()
    rank = "(f.year * 10 + CASE WHEN f.quarter = 0 THEN 5 ELSE 4 END)"
    rows = conn.execute(
        f"""
        SELECT f.ticker, f.year, f.quarter, f.revenue, f.gross_profit, f.cash,
               f.total_liabilities, f.net_income, f.operating_income,
               f.noninterest_income, f.org_type, f.balance_period, f.field_periods
        FROM catalog_financials f
        JOIN (
            SELECT f.ticker AS ticker, MAX{rank} AS rank
            FROM catalog_financials f
            WHERE f.form = :form AND f.quarter IN (0, 4)
              AND f.year IS NOT NULL AND f.year <= :last_fy
            GROUP BY f.ticker
        ) latest ON latest.ticker = f.ticker AND {rank} = latest.rank
        WHERE f.form = :form AND f.quarter IN (0, 4)
        """,
        {"form": form, "last_fy": last_fy},
    ).fetchall()
    annuals = {
        r["ticker"]: {
            "year": r["year"], "quarter": r["quarter"],
            "is_ytd": bool(r["quarter"]), "period_months": 12,
            "revenue": r["revenue"], "gross_profit": r["gross_profit"], "cash": r["cash"],
            "total_liabilities": r["total_liabilities"], "net_income": r["net_income"],
            "operating_income": r["operating_income"],
            "noninterest_income": r["noninterest_income"],
            "org_type": r["org_type"],
            "balance": _decode_balance_period(r["balance_period"]),
            "field_periods": _decode_field_periods(r["field_periods"]),
        }
        for r in rows
    }
    for ticker, row in out.items():
        annual = annuals.get(ticker)
        if (annual is None or not row.get("quarter")
                or (annual["year"] == row.get("year")
                    and annual["quarter"] == row.get("quarter"))):
            # No 12-month base, the row is annual itself, or the base IS the row
            # (a Q4 latest period is already twelve cumulative months).
            row["annual"] = None
        else:
            row["annual"] = annual


# Junk-report detector: when a parse goes wrong it reads the "Код стр" column
# instead of values, so EVERY field lands near its line code (O'zbekneftgaz
# 2023: revenue=10, net=270, liabilities=1090). A real report has at least one
# large figure, so the floor is applied to the row's maximum — never to a
# single field: small values beside large ones are genuine published figures
# (93-maxsus trest net income 952.2; DORI year-end cash 4,757.9).
_MIN_PLAUSIBLE = 10_000
_FIN_FIELDS = ("revenue", "gross_profit", "cash", "total_liabilities", "net_income", "operating_income")
_RATIO_FIELDS = ("roe", "roa", "net_profit_margin", "debt_to_equity", "current_ratio", "total_equity", "total_assets")

# Unit contract: NSBU statements and openinfo financial_indicators publish
# absolute sums in THOUSANDS of UZS ("ming so'm"), and that is how they are
# stored (catalog_financials, facts). Market caps and share prices are full
# UZS. API endpoints that serve absolute sums to the frontend multiply by this
# factor at the response boundary so the client never mixes units — dividing a
# full-UZS market cap by thousands-UZS earnings understated P/E and P/B ~1000×.
NSBU_THOUSANDS_UZS = 1000.0
FIN_MONEY_FIELDS = _FIN_FIELDS + ("noninterest_income",)
RATIO_MONEY_FIELDS = ("total_equity", "total_assets")
# The filed-balance block travels as a nested dict; its members are the same
# thousands-of-UZS sums and are scaled at the same response boundary.
BALANCE_MONEY_KEYS = _BALANCE_KEYS
# The same contract for the annual series behind the Финансы tab. It is read
# from the fact store (`financial_indicators`), whose absolute sums are in
# thousands exactly like everything else above — publishing them raw would put a
# revenue of 10 512 797 471 on screen where the issuer earned 10.5 TRILLION, and
# it would sit next to a full-UZS market cap in the same rail.
FACT_MONEY_FIELDS = ("net_revenue", "net_profit", "total_assets", "total_liabilities",
                     "total_equity")
# WHICH RATIOS THIS PLATFORM WILL STAND BEHIND.
#
# The indicator feed publishes ratios without saying what they are computed on,
# and it is not one basis. Measured against the sums we already hold, over every
# issuer-year the store has:
#
#   roe   = net_profit / total_equity      x100   225 of 225   exact
#   roa   = net_profit / total_assets      x100   674 of 674   exact
#   debt_ratio = liabilities / assets      x100   401 of 401   exact
#   total_asset_turnover = revenue/assets  x1     401 of 401   exact (a coefficient)
#   debt_to_equity                                0 of 225     NOT that identity
#   net_profit_margin = profit / revenue   x100   396 of 655   only 60 %
#
# So the first four carry a unit; debt_to_equity does not, and is published bare
# exactly as the market board shows it. `net_profit_margin` is not published at
# all — for AGBA it reads 0.05 where profit/revenue is 24.08 %, and a margin
# whose base we cannot name has no business sitting next to the sums it is
# supposedly derived from. It is DERIVED here instead, from net_profit and
# net_revenue in this same payload, and labelled as ours.
#
# gross_profit_margin and ebit_margin are dropped for the same reason and one
# more: the store rounds them to a two-decimal SHARE (0.30) and writes 0 for a
# negative margin, so UZINP's -4.77 % EBIT arrives as 0.00. We do not hold the
# numerators per year to recompute them, so they are not shown.
FACT_PERCENT_FIELDS = ("roe", "roa", "debt_ratio")
FACT_SHARE_FIELDS = ()


def _ticker_org_map(conn: sqlite3.Connection) -> dict[str, str]:
    """ticker → org_id for fact-store joins.

    Precedence: catalog_companies (available before any collector push) →
    pushed collector map (facts dataset ``org_map`` — the same org IDs the
    facts were landed under, and the only map that covers secondary lines like
    a bank's SQB2/HMBK1 issues) → ORG_OVERRIDES on top.
    """
    out: dict[str, str] = {}
    try:
        for r in conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall():
            out[str(r["ticker"]).upper()] = str(r["org_id"])
    except Exception:
        logger.exception("catalog_companies org-map read failed")
    try:
        for r in conn.execute(
            "SELECT entity_id, value_num, value_text FROM facts "
            "WHERE dataset='org_map' AND field='org_id'"
        ).fetchall():
            org = (r["value_text"] or "").strip()
            if not org and r["value_num"] is not None:
                org = str(int(r["value_num"]))
            if org:
                out[str(r["entity_id"]).upper()] = org
    except Exception:
        logger.exception("org_map facts read failed")
    for ticker, org in ORG_OVERRIDES.items():
        out[ticker] = org
    return out


def _derived_equity(fields: dict[str, float]) -> float | None:
    """Equity for issuers that don't publish it, from one period's indicators.

    The balance identity (assets − liabilities) is the primary source. When the
    period also carries ROE + net_profit, the source's own ROE identity
    (equity = net_profit/ROE·100) must agree within 25%, else the ROE identity
    wins — banks publish indicator "liabilities" that exclude deposits, so an
    unchecked balance difference can overstate their equity ~10×. Validated
    against every issuer that does publish equity: 155/155 periods within 5%.
    """
    bal = None
    assets, liab = fields.get("total_assets"), fields.get("total_liabilities")
    if assets is not None and liab is not None and assets - liab > 0:
        bal = assets - liab
    roe_eq = None
    roe, npf = fields.get("roe"), fields.get("net_profit")
    # |ROE| < 0.1%: the published 2-decimal rounding dominates the estimate.
    if roe and npf is not None and abs(roe) >= 0.1 and npf / roe > 0:
        roe_eq = npf / roe * 100.0
    if bal is not None and roe_eq is not None:
        return bal if abs(bal - roe_eq) / roe_eq <= 0.25 else roe_eq
    return bal if bal is not None else roe_eq


def get_all_ratios() -> dict[str, dict[str, Any]]:
    """Latest per-ticker financial ratios and equity from the fact store
    (openinfo ``financial_indicators``), keyed by ticker.

    Feeds the market-wide multiplier columns (P/E, P/B) and ratio coefficients
    (ТЗ §3.8). Ratios are served exactly as openinfo reports them; equity/assets
    are absolute sums used to derive P/B (= market_cap / equity), with equity
    derived from the same-period balance/ROE identities for the majority of
    issuers that never publish it directly. Unreliable ticker→org matches are
    skipped, mirroring the financials enrichment.
    """
    fetch_fields = tuple(dict.fromkeys(_RATIO_FIELDS + ("total_liabilities", "net_profit")))
    conn = get_catalog_conn()
    try:
        ticker_org = _ticker_org_map(conn)
        rows = conn.execute(
            "SELECT entity_id, field, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND value_num IS NOT NULL "
            f"AND field IN ({','.join('?' * len(fetch_fields))})",
            fetch_fields,
        ).fetchall()
    except Exception:
        conn.close()
        return {}
    best: dict[tuple[str, str], tuple[str, float]] = {}
    by_period: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        key = (str(r["entity_id"]), r["field"])
        period = str(r["period"] or "")
        if _period_key(period) == (0, 0):
            continue  # corrupt/unparseable source period — never a candidate
        # A premature current-year annual (openinfo's in-progress placeholder)
        # must not win "latest period" over a real completed period; _fact_period_rank
        # demotes it so it only surfaces when it is an issuer's sole datum.
        if best.get(key) is None or _fact_period_rank(period) > _fact_period_rank(best[key][0]):
            best[key] = (period, r["value_num"])
        by_period.setdefault((str(r["entity_id"]), period), {})[r["field"]] = r["value_num"]
    # Latest derivable equity per org, for issuers with no published figure.
    derived_eq: dict[str, tuple[str, float]] = {}
    # openinfo publishes debt_to_equity_ratio = 0 for many issuers whose own
    # balance figures say otherwise (UTYK: 98.1B liabilities on 222.8B equity,
    # published 0). Derive liabilities/equity per period, but only when the
    # balance identity (assets − liabilities ≈ equity within 25%) holds — for
    # banks the indicator "liabilities" excludes deposits, so a failed identity
    # means the inputs can't be trusted for this (banks publish real D/E anyway).
    derived_de: dict[str, tuple[str, float]] = {}
    for (org, period), fields in by_period.items():
        eq = _derived_equity(fields)
        if eq is None:
            continue
        cur = derived_eq.get(org)
        if cur is None or _fact_period_rank(period) > _fact_period_rank(cur[0]):
            derived_eq[org] = (period, eq)
        liab = fields.get("total_liabilities")
        assets = fields.get("total_assets")
        eq_pub = fields.get("total_equity") or eq
        if (liab is not None and liab >= 0 and assets and eq_pub and eq_pub > 0
                and abs((assets - liab) - eq_pub) / eq_pub <= 0.25):
            cur = derived_de.get(org)
            if cur is None or _fact_period_rank(period) > _fact_period_rank(cur[0]):
                derived_de[org] = (period, round(liab / eq_pub, 2))
    out: dict[str, dict[str, Any]] = {}
    for ticker, org in ticker_org.items():
        if ticker in UNRELIABLE_FINANCIALS:
            continue
        entry: dict[str, Any] = {}
        latest_period = None
        for field in _RATIO_FIELDS:
            hit = best.get((org, field))
            if hit is not None:
                entry[field] = hit[1]
                if latest_period is None or _fact_period_rank(hit[0]) > _fact_period_rank(latest_period):
                    latest_period = hit[0]
        if entry and entry.get("total_equity") is None:
            hit = derived_eq.get(org)
            if hit is not None:
                entry["total_equity"] = hit[1]
                if latest_period is None or _fact_period_rank(hit[0]) > _fact_period_rank(latest_period):
                    latest_period = hit[0]
        if entry and not entry.get("debt_to_equity"):
            hit = derived_de.get(org)
            if hit is not None:
                entry["debt_to_equity"] = hit[1]
        if entry:
            entry["period"] = latest_period
            out[ticker] = entry
    conn.close()
    return out


def _row_period(fin: dict[str, Any]) -> str | None:
    """The fact-store period string a financials row is labelled with.

    ``{'year': 2024, 'quarter': 0}`` -> ``'2024'`` (annual); quarter 1-4 ->
    ``'2024Q1'``. Returns None when the row carries no usable year.
    """
    year = fin.get("year")
    if not isinstance(year, int) or year <= 0:
        return None
    quarter = fin.get("quarter") or 0
    return f"{year}Q{quarter}" if 1 <= quarter <= 4 else str(year)


def _enrich_financials_from_facts(conn: sqlite3.Connection, out: dict[str, dict[str, Any]]) -> None:
    """Conservatively correct NSBU headline figures from the fact store.

    openinfo's financial_indicators are cleaner than the NSBU form-2 parse, but the
    ticker→org resolution is ambiguous for some issuers (openinfo carries duplicate
    org records and UZSE names fuzzy-match unrelated entities), so a fact could be
    for the *wrong* company. We therefore only apply changes we can trust:
      - banks (null NSBU revenue): fill revenue and take net_profit;
      - sign flips: NSBU net_income of the same magnitude but opposite sign to the
        fact — unambiguously the same company, a parser sign error;
      - fill genuinely-null revenue / total_liabilities;
      - blank implausibly small NSBU values (clear parse errors).
    Large magnitude disagreements are left as flags (see audit_financials_consistency)
    rather than "corrected" with possibly-wrong-org data.

    PERIOD DISCIPLINE. A row carries one (year, quarter) label, and every value in
    it must belong to that period or say which period it does belong to. The fact
    store's "latest indicator on file" is frequently a *different, older* period
    than the parsed NSBU row, so:

      - a fact for the row's OWN period may overwrite the parsed value (same
        period, cleaner source — this is the intended correction);
      - a fact for any other period may only FILL A NULL, never overwrite, and the
        period it came from is recorded in ``fin['field_periods']``.

    Without that rule the enrichment wrote FY2024 revenue into a row labelled
    "Q1 2026 (3 months)" — a ~5.5x overstatement on UZMK that also destroyed the
    fresher quarterly figure underneath it. Every finance-sector and ORG_OVERRIDES
    issuer was exposed.
    """
    srcs = ("net_revenue", "net_profit", "total_liabilities",
            "gross_profit_margin", "ebit_margin")
    try:
        comp = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall()
        rows = conn.execute(
            "SELECT entity_id, field, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND value_num IS NOT NULL "
            f"AND field IN ({','.join('?' * len(srcs))})",
            srcs,
        ).fetchall()
    except Exception:
        return
    ticker_org = {r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"])) for r in comp}
    # Field-level fills verified by hand against the issuer's actual filings —
    # used only where the automated chain cannot reach a figure the source
    # publishes. Each entry cites its provenance.
    curated: dict[str, dict[str, float]] = {
        # National Investment Fund: openinfo net_revenue is literally 0.0 (a
        # fund has no sales revenue) — a true published zero, not a gap.
        "UZNF": {"revenue": 0.0},
        # Muborakneftgazmontaj: form 2 publishes Валовая прибыль = 0 (стр.030;
        # a dividend-income holding with no product sales) — a true zero.
        "MNGM": {"gross_profit": 0.0},
        # O'zbekiston neftgaz: 2021+ NSBU filings are zero stubs; the 2020
        # annual (same year as the indicator facts shown for it) publishes
        # year-end cash 2,291,908,931 th UZS (form 1, стр.320). The alias step
        # copies it onto the sibling UZNG line.
        "UZNGP": {"cash": 2291908931.0},
    }
    best: dict[tuple[str, str], tuple[str, float]] = {}
    # Every (org, field) indexed by its exact period, so a fill can prefer the fact
    # that belongs to the period the row is labelled with.
    by_period: dict[tuple[str, str, str], float] = {}
    # net_profit indexed by annual year, so a sign-flip check compares against the
    # SAME year the board displays — not merely the newest indicator on file (which
    # can be a later annual than the parsed NSBU set, defeating the magnitude test).
    npf_by_year: dict[tuple[str, int], float] = {}
    for r in rows:
        key = (str(r["entity_id"]), r["field"])
        period = str(r["period"] or "")
        if _period_key(period) == (0, 0):
            continue  # corrupt/unparseable source period — never a candidate
        if not r["value_num"]:
            # openinfo publishes all-zero indicator years for non-filers
            # (O'zbekneftgaz 2021-2024) — a zero is "no report", not a figure.
            # Letting it win "latest period" would shadow the last real year.
            continue
        if _is_premature_annual_period(period):
            continue  # openinfo's in-progress current-year placeholder — not a real annual
        if best.get(key) is None or _fact_period_rank(period) > _fact_period_rank(best[key][0]):
            best[key] = (period, r["value_num"])
        by_period[(str(r["entity_id"]), r["field"], period)] = r["value_num"]
        if r["field"] == "net_profit" and period.isdigit() and len(period) == 4:
            npf_by_year[(str(r["entity_id"]), int(period))] = r["value_num"]
    for ticker, fin in out.items():
        # Tickers whose only openinfo match is a different company: blank rather
        # than show another entity's figures.
        if ticker in UNRELIABLE_FINANCIALS:
            for key in _FIN_FIELDS:
                fin[key] = None
            continue
        # is_bank is judged on the issuer's sector — a stable signal. (Using
        # "revenue is None" would misfire after blanking or on a re-read of already
        # enriched-and-pushed data, making a blanked value look like a bank.)
        is_bank = COMPANY_SECTORS.get(ticker) == "finance"
        row_max = max((abs(fin[k]) for k in _FIN_FIELDS if fin.get(k)), default=0.0)
        if 0 < row_max < _MIN_PLAUSIBLE:
            for key in _FIN_FIELDS:
                fin[key] = None
        # After junk-blanking so a curated figure survives it (UZNGP's junk
        # 2023 row carried code-values that both hid and then erased cash).
        for key, val in curated.get(ticker, {}).items():
            if fin.get(key) is None:
                fin[key] = val
        org = ticker_org.get(ticker)
        if not org:
            continue
        row_period = _row_period(fin)

        def _pick(field: str) -> tuple[str, float] | None:
            """The fact to use for ``field``: the row's own period if it exists,
            otherwise the newest one on file (which the caller must then treat as
            fill-only, because it describes a different reporting period)."""
            if row_period is not None:
                same = by_period.get((org, field, row_period))
                if same is not None:
                    return (row_period, same)
            return best.get((org, field))

        def _apply(target: str, hit: tuple[str, float] | None) -> None:
            """Write a fact onto the row under the period rule (see the docstring).

            Same period as the row -> authoritative, overwrite. Different period ->
            fill a null only, and record the period the figure actually describes so
            nothing is served under the wrong label.
            """
            if hit is None:
                return
            period, value = hit
            if period == row_period:
                fin[target] = value
                return
            if fin.get(target) is not None:
                # A real figure for this row's period already exists; a different
                # period's indicator does not get to replace it. Visible via
                # audit_financials_consistency rather than silently resolved.
                logger.debug(
                    "%s: keeping parsed %s for %s, not overwriting with the %s fact",
                    ticker, target, row_period, period,
                )
                return
            fin[target] = value
            fin.setdefault("field_periods", {})[target] = period

        rev = _pick("net_revenue")
        npf = _pick("net_profit")
        tl = _pick("total_liabilities")
        rev_v = rev[1] if rev and rev[1] not in (None, 0) else None
        npf_v = npf[1] if npf and npf[1] is not None else None
        tl_v = tl[1] if tl and tl[1] not in (None, 0) else None

        def _derive_margin_lines() -> None:
            # Gross/operating profit from the SAME-period published margin ×
            # revenue (verified against O'zbekneftgaz 2019, where the filed
            # figures reproduce the margins exactly). Fraction-valued margins
            # only — openinfo stores net_profit_margin in percent but gross/
            # ebit margins as fractions, and a mixed-unit hit would be junk.
            if rev is None or not rev[1]:
                return
            for fld, margin_key in (("gross_profit", "gross_profit_margin"),
                                    ("operating_income", "ebit_margin")):
                if fin.get(fld) is not None:
                    continue
                m = by_period.get((org, margin_key, rev[0]))
                if m is not None and 0 < m <= 1:
                    fin[fld] = round(rev[1] * m)
                    # The derived line inherits the revenue's period, which is not
                    # always the row's — carry that through, same rule as _apply.
                    if rev[0] != row_period:
                        fin.setdefault("field_periods", {})[fld] = rev[0]

        if ticker in ORG_OVERRIDES:
            # Org is human-verified, so openinfo's clean figures are authoritative
            # FOR THEIR OWN PERIOD. _apply still refuses to write a figure from one
            # period into a row labelled with another — a verified org says nothing
            # about which reporting period a number belongs to, and this branch is
            # where the UZMK "Q1 2026 carrying FY2024 revenue" overstatement came
            # from.
            _apply("net_income", npf if npf_v is not None else None)
            _apply("revenue", rev if rev_v is not None else None)
            _apply("total_liabilities", tl if tl_v is not None else None)
            _derive_margin_lines()
            continue

        # Finance issuers (banks and insurers): openinfo's net_revenue is the
        # authoritative top line. Banks have no NSBU revenue line at all; insurers
        # do (gross written premiums), but we show the net-of-reinsurance indicator
        # to stay consistent with how bank revenue is sourced. Non-finance keep the
        # NSBU figure and only fall back to the indicator when it is blank.
        if rev_v is not None and (is_bank or fin.get("revenue") is None):
            _apply("revenue", rev)
        if npf_v is not None:
            stored = fin.get("net_income")
            if is_bank and npf_v != 0:
                _apply("net_income", npf)
            elif stored is not None:
                year = fin.get("year")
                cmp_v = npf_by_year.get((org, year)) if year else None
                if cmp_v is None:
                    cmp_v = npf_v
                same_magnitude = abs(abs(stored) - abs(cmp_v)) / max(abs(cmp_v), 1.0) < 0.05
                if same_magnitude and (stored < 0) != (cmp_v < 0):
                    # A sign flip is a parser error on THIS row's own figure, not a
                    # different period's value — the magnitude test already proved
                    # they are the same number, so the label stays correct.
                    fin["net_income"] = cmp_v
        if fin.get("total_liabilities") is None and tl_v is not None:
            _apply("total_liabilities", tl)
        _derive_margin_lines()


def purge_premature_annual_facts() -> int:
    """Delete ``financial_indicators`` facts for a not-yet-complete fiscal year.

    openinfo hands out a placeholder *annual* (quarter 0) indicator for the
    in-progress year; the collector now skips it, but a catalog populated before
    that guard can still carry the row. Left in place it keeps an issuer whose only
    fact is that placeholder "covered", blocking the NSBU-derived collector from
    re-covering it — so purge it. Quarterly current-year periods ('2026Q1') carry a
    'Q' and are not matched. Idempotent; safe to call each collector cycle.
    """
    cutoff = _latest_complete_fiscal_year()
    conn = get_catalog_conn()
    with conn:
        cur = conn.execute(
            "DELETE FROM facts WHERE dataset='financial_indicators' "
            "AND period GLOB '20[0-9][0-9]' AND CAST(period AS INT) > ?",
            (cutoff,),
        )
        n = cur.rowcount
    conn.close()
    if n:
        logger.info("purged %d premature (> FY%d) annual financial_indicators facts", n, cutoff)
    return n


def upsert_facts(rows: list[dict[str, Any]]) -> int:
    """Upsert generic facts from any source adapter (forward-compatible storage).

    Each row: ``entity_id, dataset, field, value`` (+ optional ``period, unit,
    source, source_url``). Numeric values land in ``value_num``, others in
    ``value_text``. New datasets/fields require no schema change.
    """
    if not rows:
        return 0
    conn = get_catalog_conn()
    written = 0
    with conn:
        for r in rows:
            value = r.get("value")
            vnum = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            vtext = None if vnum is not None else (str(value) if value is not None else None)
            conn.execute(
                """
                INSERT INTO facts (entity_id, dataset, field, period, value_num, value_text, unit, source, source_url, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(entity_id, dataset, field, period, source) DO UPDATE SET
                    value_num  = excluded.value_num,
                    value_text = excluded.value_text,
                    unit       = excluded.unit,
                    source_url = excluded.source_url,
                    fetched_at = datetime('now')
                """,
                (str(r["entity_id"]), r["dataset"], r["field"], str(r.get("period", "")),
                 vnum, vtext, r.get("unit"), r.get("source", "unknown"), r.get("source_url")),
            )
            written += 1
        _cleanup_invalid_fact_periods(conn)
    conn.close()
    # The ratio memo is derived from exactly these rows.
    invalidate_ratios_cache()
    return written


def _cleanup_invalid_fact_periods(conn: sqlite3.Connection) -> int:
    """Delete dated facts whose period fails validation ('2025Q7', '2026Q5', …).

    Runs on every fact upsert (local collect and prod admin push alike), so a
    DB that already contains corrupt periods heals itself without a hand-run
    migration. Period-less facts (period = '') are untouched.
    """
    periods = [
        r["period"]
        for r in conn.execute("SELECT DISTINCT period FROM facts WHERE period != ''").fetchall()
    ]
    bad = [p for p in periods if _period_key(p) == (0, 0)]
    removed = 0
    for p in bad:
        removed += conn.execute("DELETE FROM facts WHERE period = ?", (p,)).rowcount
    if removed:
        logger.warning("fact store: removed %d rows with invalid periods %s", removed, bad)
        invalidate_ratios_cache()
    return removed


def get_facts(entity_id: Any = None, dataset: str | None = None) -> list[dict[str, Any]]:
    """Query the fact store, optionally filtered by entity (org_id) and dataset."""
    conn = get_catalog_conn()
    query = "SELECT * FROM facts WHERE 1=1"
    params: list[Any] = []
    if entity_id is not None:
        query += " AND entity_id = ?"
        params.append(str(entity_id))
    if dataset:
        query += " AND dataset = ?"
        params.append(dataset)
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return rows


def audit_financials_consistency(form: str = "NSBU", tol: float = 0.05) -> list[dict[str, Any]]:
    """Reconcile served net_income against the authoritative fact-store net_profit.

    Flags any issuer whose stored/served net income differs by more than ``tol``
    from openinfo's own net_profit for the same entity — catching mislabels
    (revenue booked as profit) or stale NSBU parses before they mislead a user.
    """
    served = get_all_financials(form)
    conn = get_catalog_conn()
    try:
        comp = {
            r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"]))
            for r in conn.execute(
                "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT entity_id, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND field='net_profit' AND value_num IS NOT NULL"
        ).fetchall()
    except Exception:
        conn.close()
        return []
    conn.close()
    best: dict[str, tuple[str, float]] = {}
    for r in rows:
        key = str(r["entity_id"])
        period = str(r["period"] or "")
        if _period_key(period) == (0, 0):
            continue  # corrupt/unparseable source period
        if key not in best or _period_key(period) > _period_key(best[key][0]):
            best[key] = (period, r["value_num"])
    flags: list[dict[str, Any]] = []
    for ticker, fin in served.items():
        ni = fin.get("net_income")
        org = comp.get(ticker)
        if ni is None or not org:
            continue
        hit = best.get(org)
        if not hit or not hit[1]:
            continue
        if abs(ni - hit[1]) / max(abs(hit[1]), 1.0) > tol:
            flags.append({"ticker": ticker, "stored_net_income": ni, "authoritative_net_profit": hit[1]})
    return flags


def get_catalog_coverage(form: str = "NSBU") -> dict[str, dict[str, Any]]:
    """Per-ticker data coverage from the catalog DB (for /api/coverage).

    Returns {ticker: {org_id, reports, has_financials, sync_error, last_synced_at}}
    so the API can show, for every listed security, whether each dataset is
    filled / empty / failed — no openinfo access required (reads the local cache).
    """
    conn = get_catalog_conn()
    comp = {
        r["ticker"]: {
            "org_id": r["org_id"],
            "sync_error": r["sync_error"],
            "last_synced_at": r["last_synced_at"],
        }
        for r in conn.execute(
            "SELECT ticker, org_id, sync_error, last_synced_at FROM catalog_companies"
        ).fetchall()
    }
    rep_counts = {
        r["ticker"]: r["c"]
        for r in conn.execute(
            "SELECT ticker, COUNT(*) AS c FROM catalog_reports GROUP BY ticker"
        ).fetchall()
    }
    conn.close()
    fin = get_all_financials(form)
    out: dict[str, dict[str, Any]] = {}
    tickers = set(comp) | set(rep_counts) | set(fin)
    for tk in tickers:
        info = comp.get(tk, {})
        out[tk] = {
            "org_id": info.get("org_id"),
            "sync_error": info.get("sync_error"),
            "last_synced_at": info.get("last_synced_at"),
            "reports": rep_counts.get(tk, 0),
            "has_financials": tk in fin,
        }
    return out


def _inherit_financials_by_org(conn: sqlite3.Connection, out: dict[str, dict[str, Any]]) -> None:
    """Let every listed ticker inherit its issuer's financials (ТЗ data pipeline).

    Preferred shares (HMKBP) share the issuer org of the ordinary share (HMKB);
    bonds share the issuer that files the statements. Financials are computed per
    issuer (org_id) but stored under whatever ticker was synced, so a pref/bond
    ends up with an org resolved but no financials row. This maps every ticker in
    catalog_companies to its org's financials when it has none of its own — the
    values are identical because it is the same legal entity.
    """
    try:
        comp = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall()
    except Exception:
        return
    ticker_org: dict[str, str] = {r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"])) for r in comp}
    # One financials payload per org (any ticker of that org that already has one).
    org_fin: dict[str, dict[str, Any]] = {}
    for ticker, fin in out.items():
        org = ticker_org.get(ticker)
        if org and org not in org_fin:
            org_fin[org] = fin
    # Assign to sibling tickers that have an org but no financials of their own.
    for ticker, org in ticker_org.items():
        if ticker in out:
            continue
        source = org_fin.get(org)
        if source:
            # field_periods must be copied, not aliased: the enrichment pass that
            # runs after this one mutates it per ticker, and siblings can resolve to
            # different org records (UZMK/UZMKP), so a shared dict would leak one
            # ticker's provenance onto another's row.
            out[ticker] = {**source, "field_periods": dict(source.get("field_periods") or {}),
                           "annual": dict(source["annual"]) if source.get("annual") else None,
                           "inherited_from_org": org}

    # Preferred shares also inherit directly from their ordinary ticker, even when
    # openinfo indexes them under a different org record (duplicate org entries for
    # the same issuer, e.g. UZMK/UZMKP). Same legal entity → same financials.
    for ticker in list(ticker_org.keys()):
        if ticker in out or not ticker.endswith("P"):
            continue
        base = ticker[:-1]
        if base in out:
            out[ticker] = {**out[base], "field_periods": dict(out[base].get("field_periods") or {}),
                           "annual": dict(out[base]["annual"]) if out[base].get("annual") else None,
                           "inherited_from_ticker": base}


def _fin_candidates(conn: sqlite3.Connection, form: str, ttl_days: int,
                    tickers: list[str] | None) -> list[dict[str, Any]]:
    """Best parseable report per ticker lacking a fresh cache.

    Considers only reports that have an Excel export (PDF-only issuers can't be
    parsed). Selection rules, in order:

      * a premature annual (fiscal year not yet ended — openinfo's current-year
        placeholder) is never a candidate;
      * the annual for the most recent *completed* fiscal year wins outright — it
        is the honest full-year figure, preferred over any fresher partial quarter;
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
         AND f.updated_at >= datetime('now', ?)
        WHERE r.report_form = ? AND r.excel_url IS NOT NULL
          AND r.year IS NOT NULL {ticker_filter}
          AND f.ticker IS NULL
        """,
        params,
    ).fetchall()
    last_fy = _latest_complete_fiscal_year()
    best: dict[str, tuple] = {}
    for r in rows:
        t = r["ticker"]
        year = r["year"]
        quarter = r["quarter"] or 0
        is_annual = r["period_type"] == "annual"
        if is_annual and year is not None and year > last_fy:
            continue  # premature placeholder annual — never a candidate
        if is_annual and year == last_fy:
            key = (2, year, 1, 0)  # most-recent completed annual: outranks partial quarters
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
    conn = get_catalog_conn()
    have = {r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM catalog_reports").fetchall()}
    conn.close()
    pending = [
        t for t in _TICKER_TO_NAME
        if t not in have and not (t.endswith("P") and t[:-1] in _TICKER_TO_NAME)
    ]
    synced = 0
    for ticker in pending[:sync_limit]:
        try:
            sync_company(ticker, _TICKER_TO_NAME.get(ticker, ticker))
            synced += 1
        except Exception:
            logger.exception("warmup catalog sync failed for %s", ticker)
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
    conn = get_catalog_conn()
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
        if yq[1] == 0 and _is_premature_annual_year(yq[0]):
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
    from openinfo_collector import fetch_report_documents, parse_nsbu_pdf_financials

    conn = get_catalog_conn()
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

    session = _make_session()
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
        c = get_catalog_conn()
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
        logger.info("pdf fallback: skipped %d ticker(s) with no resolved org id: %s",
                    len(unresolved), ", ".join(sorted(unresolved)[:20]))
    return {"ok": True, "candidates": len(best), "updated": updated,
            "updated_tickers": updated_tickers,
            "skipped_unresolved": len(unresolved), "errors": errors[:10]}


# Fields whose value the six headline indicators are read from. Recorded against
# the report so a figure can be traced to its filing (ТЗ Дополнение 1 §Б.4).
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
            {"field": k, "value": values[k], "unit_scale": NSBU_THOUSANDS_UZS}
            for k in usable
        ])
        provenance.set_state(report_id, "validated")
        return report_id
    except Exception:  # noqa: BLE001 — provenance must never break a collection
        logger.exception("provenance: could not register parse for %s %s %s", ticker, year, quarter)
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
            logger.exception("provenance: backfill could not seed the registry")
            return {"linked": 0, "unresolved": 0}

    conn = get_catalog_conn()
    try:
        rows = conn.execute(
            "SELECT ticker, form, year, quarter, revenue, gross_profit, cash, "
            "       total_liabilities, net_income, operating_income "
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
        figures = [{"field": k, "value": row[k], "unit_scale": NSBU_THOUSANDS_UZS}
                   for k in _FINANCIAL_KEYS if row[k] is not None]
        if figures:
            figure_items.append((report_id, figures))
            validated.append(report_id)
        links.append((report_id, row["ticker"], row["form"], row["year"], row["quarter"]))
        linked += 1

    provenance.record_figures_bulk(figure_items)
    # Several tickers of one issuer resolve to one report; state it once.
    provenance.set_state_bulk(list(dict.fromkeys(validated)), "validated")
    if links:
        conn = get_catalog_conn()
        try:
            with conn:
                conn.executemany(
                    "UPDATE catalog_financials SET report_id=? WHERE ticker=? AND form=? "
                    "AND year=? AND quarter=?", links)
        finally:
            conn.close()
    logger.info("provenance backfill: linked %d, unresolved %d", linked, unresolved)
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
    limit = limit or FINANCIALS_BATCH
    ttl_days = ttl_days if ttl_days is not None else FINANCIALS_TTL_DAYS
    sync_limit = FINANCIALS_SYNC_BATCH if sync_limit is None else sync_limit
    if not _FIN_LOCK.acquire(blocking=False):
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
            logger.exception("provenance: catalog sync failed")
        conn = get_catalog_conn()
        candidates = _fin_candidates(conn, form, ttl_days, tickers)
        conn.close()
        for cand in candidates[:limit]:
            ticker, year, quarter = cand["ticker"], cand["year"], cand["quarter"]
            processed += 1
            try:
                data = fetch_report_excel_data(ticker, form, year, quarter)
                ratios = compute_financial_ratios(data.get("income"), data.get("balance")) if data.get("ok") else {}
                vals = (ratios.get("source_values") or {}) if ratios else {}
                if not any(vals.get(k) is not None for k in _FINANCIAL_KEYS):
                    # Preferred (annual) report had no usable data — e.g. an old
                    # empty filing. Fall back to the ticker's most recent report.
                    alt = _latest_excel_report(ticker, form, exclude=(year, quarter or 0))
                    if alt:
                        alt_data = fetch_report_excel_data(ticker, form, alt["year"], alt["quarter"])
                        if alt_data.get("ok"):
                            alt_ratios = compute_financial_ratios(alt_data.get("income"), alt_data.get("balance"))
                            alt_vals = alt_ratios.get("source_values") or {}
                            if any(alt_vals.get(k) is not None for k in _FINANCIAL_KEYS):
                                year, quarter, vals, ratios = alt["year"], alt["quarter"], alt_vals, alt_ratios
                # ТЗ Дополнение 1 §Б.2/§Б.3: the report this parse consumed moves
                # through its states and the figures are recorded against it, so
                # every number we publish can name the filing it came from. A
                # failure here is logged and never allowed to stop the parse —
                # provenance is a record of the work, not a precondition for it.
                report_id = _register_parse(ticker, form, year, quarter, data, vals)
                if any(vals.get(k) is not None for k in _FINANCIAL_KEYS):
                    upsert_financials_cache(ticker, form, year, quarter, vals, report_id)
                    # Cache the ratios computed from the same statements: this is
                    # what fills the company-page Key Metrics block and sector
                    # averages — previously only a manual, login-gated analysis
                    # wrote them, so catalog_ratios stayed empty for everyone.
                    metrics = (ratios or {}).get("metrics") or {}
                    if any(v is not None for v in metrics.values()):
                        upsert_ratio_cache(ticker, form, year, quarter or 0, metrics)
                    filled += 1
            except Exception:
                logger.exception("financials refresh failed for %s", ticker)
        return {"ok": True, "synced": synced, "candidates": len(candidates),
                "processed": processed, "filled": filled}
    finally:
        _FIN_LOCK.release()


def get_financials_series(ticker: str, form: str = "NSBU") -> dict[str, dict[str, Any]]:
    """Every ANNUAL period this platform has parsed for one issuer, by year.

    Straight from the filings — catalog_financials for the sums and
    catalog_ratios for the ratios computed off the same two statements. This is
    the authority: the openinfo indicator feed it replaces had UZTL's 2023 and
    2024 revenue transposed and 2021 missing, while the filings agree with it
    everywhere it is right.

    Sums stay in the stored unit (thousands); the caller scales them, exactly as
    every other endpoint that serves absolute figures does.
    """
    t = str(ticker or "").strip().upper()
    if not t:
        return {}
    conn = get_catalog_conn()
    try:
        # By the ISSUER, not the ticker: a filing lands in the cache under
        # whichever share class it was catalogued under, and reading one class
        # alone left UZASP, UZTLP, UZIRP and the other preferred lines with no
        # filed years at all while their ordinary sibling showed a decade.
        siblings = _org_siblings(conn, t) or [t]
        placeholders = ",".join("?" * len(siblings))
        fin = conn.execute(
            f"SELECT ticker, year, {', '.join(_FIN_FIELDS)} FROM catalog_financials "
            f"WHERE ticker IN ({placeholders}) AND form=? AND quarter=0 ORDER BY year",
            (*siblings, form)).fetchall()
        rat = conn.execute(
            "SELECT ticker, year, roa, roe, debt_ratio, debt_to_equity FROM catalog_ratios "
            f"WHERE ticker IN ({placeholders}) AND form=? AND quarter=0 ORDER BY year",
            (*siblings, form)).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    # Siblings first, the requested ticker last: where both classes carry the
    # same year (the same filing parsed twice) the requested one wins.
    for row in sorted(fin, key=lambda r: r["ticker"] == t):
        out.setdefault(str(row["year"]), {}).update(
            {k: row[k] for k in _FIN_FIELDS if row[k] is not None})
    for row in sorted(rat, key=lambda r: r["ticker"] == t):
        out.setdefault(str(row["year"]), {}).update(
            {k: row[k] for k in ("roa", "roe", "debt_ratio", "debt_to_equity")
             if row[k] is not None})
    return out


def get_sector_averages(sector_tickers: list[str], form: str, year: int) -> dict[str, Any]:
    if not sector_tickers:
        return {}
    conn = get_catalog_conn()
    placeholders = ",".join("?" * len(sector_tickers))
    row = conn.execute(
        f"""
        SELECT AVG(roa) as roa, AVG(roe) as roe, AVG(net_margin) as net_margin,
               AVG(debt_ratio) as debt_ratio, AVG(debt_to_equity) as debt_to_equity,
               COUNT(*) as n
        FROM catalog_ratios
        WHERE ticker IN ({placeholders}) AND form=? AND year=? AND quarter=0
        """,
        (*sector_tickers, form, year),
    ).fetchone()
    conn.close()
    if not row or not row["n"]:
        return {}
    return {
        "ROA": round(row["roa"], 2) if row["roa"] is not None else None,
        "ROE": round(row["roe"], 2) if row["roe"] is not None else None,
        "net_margin": round(row["net_margin"], 2) if row["net_margin"] is not None else None,
        "debt_ratio": round(row["debt_ratio"], 2) if row["debt_ratio"] is not None else None,
        "debt_to_equity": round(row["debt_to_equity"], 2) if row["debt_to_equity"] is not None else None,
        "n": row["n"],
    }


def get_recent_new_reports(since_days: int = 120, limit: int = 80) -> list[dict[str, Any]]:
    """Recently detected new report filings across every ticker — the source for
    the public market-news feed (ТЗ §3.2 item 6)."""
    conn = get_catalog_conn()
    rows = conn.execute(
        """
        SELECT ticker, report_form, period_type, year, quarter, title, detected_at
        FROM catalog_new_reports
        WHERE detected_at >= datetime('now', ?)
        ORDER BY detected_at DESC
        LIMIT ?
        """,
        (f"-{max(1, since_days)} days", max(1, limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_new_reports_for_tickers(tickers: list[str], since_days: int = 7) -> list[dict[str, Any]]:
    """Return recently detected new reports for the given tickers (used for notifications)."""
    if not tickers:
        return []
    conn = get_catalog_conn()
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


# ---------------------------------------------------------------------------
# Excel data access
# ---------------------------------------------------------------------------

def fetch_report_excel_data(ticker: str, form: str, year: int, quarter: int) -> dict[str, Any]:
    urls = get_report_urls(ticker, form, year, quarter)
    if not urls:
        return {"ok": False, "income": None, "balance": None, "error": "Report not found in catalog"}

    session = _make_session()
    income: dict | None = None
    balance: dict | None = None
    errors: list[str] = []

    if urls.get("excel_url"):
        doc = {"excel_url": urls["excel_url"], "id": None, "object_id": None,
               "published_at": urls.get("published_at"), "period_type": urls.get("period_type"),
               "report_form": form, "title": urls.get("title")}
        try:
            parsed = parse_excel_report_document(session, doc)
            if parsed.get("ok"):
                income = parsed
            else:
                errors.append(f"income/main: {parsed.get('error')}")
        except Exception as exc:
            errors.append(f"income/main: {exc}")

    if urls.get("excel_url_form1"):
        doc1 = {"excel_url": urls["excel_url_form1"], "id": None, "object_id": None,
                "published_at": urls.get("published_at"), "period_type": urls.get("period_type"),
                "report_form": form, "title": urls.get("title")}
        try:
            parsed1 = parse_excel_report_document(session, doc1)
            if parsed1.get("ok"):
                balance = parsed1
            else:
                errors.append(f"balance: {parsed1.get('error')}")
        except Exception as exc:
            errors.append(f"balance: {exc}")

    ok = income is not None or balance is not None
    return {
        "ok": ok,
        "income": income,
        "balance": balance,
        "error": "; ".join(errors) if errors and not ok else None,
        "warnings": errors if ok and errors else [],
    }


# ---------------------------------------------------------------------------
# Financial ratio computation
# ---------------------------------------------------------------------------

_LABEL_PATTERNS: dict[str, list[str]] = {
    "revenue": ["выруч", "реализац", "revenue", "sales", "daromad", "tushum"],
    "net_income": ["чистая прибыл", "чистый доход", "чистый убыт",
                   "net income", "net profit", "net loss", "sof foyda"],
    # Commercial form №1 totals assets as "Всего по активу баланса (стр.130+390)"
    # (uz: "balans aktivi bo'yicha jami") — neither contains "итого актив".
    "total_assets": ["итого актив", "total asset", "всего актив", "jami aktiv",
                     "по активу баланса", "balans aktivi"],
    "equity": ["собственный капитал", "итого капитал", "капитал и резерв",
               "total equity", "equity", "o'z kapitali", "kapital"],
    "total_liabilities": ["итого обязательств", "всего обязательств",
                          "total liabilit", "majburiyat"],
    # Commercial NSBU balance has no single "итого обязательств" line — liabilities
    # split into long-term (стр.490) + current (стр.600); summed as a fallback.
    "lt_liabilities": ["долгосрочные обязательства"],
    "cur_liabilities": ["текущие обязательства", "краткосрочные обязательства"],
    # Валовая прибыль (форма №2): "Валовая прибыль (убыток) от реализации ..."
    "gross_profit": ["валовая прибыл", "валовой доход", "валовая выручка",
                     "gross profit", "yalpi foyda"],
    # Наличность в кассе (форма №1, баланс) = «Денежные средства на расчетном
    # счете (5100)», стр. 340 в форме АО / 430 в страховой форме — операционный
    # остаток на банковском счете, а НЕ свод «Денежные средства, всего», куда
    # входят касса (5000), валютные счета (5200) и эквиваленты (5500/5600/5700).
    "cash_account": ["расчетном счете", "расчётном счёте", "расчетном счёте",
                     "расчетный счет", "расчётный счёт", "(5100)",
                     "hisob-kitob schyot", "settlement account"],
    # Свод — запасной вариант для форм без строки 5100 (банковская форма её не
    # публикует: там «Кассовая наличность и другие платежные документы»).
    "cash": ["денежные средства", "денежных средств", "наличность", "касса",
             "cash and cash", "cash equivalent", "pul mablag", "kassa"],
    # Операционный доход = прибыль (убыток) от основной деятельности (форма №2,
    # стр. 100). Паттерны требуют "прибыль/убыток", чтобы не поймать стр. 090
    # "Прочие доходы от основной деятельности".
    "operating_income": ["прибыль (убыток) от основной деятельности",
                         "прибыль от основной деятельности",
                         "убыток от основной деятельности",
                         "операционная прибыл", "операционный доход",
                         "operating income", "operating profit"],
    # The bank form has no «выручка» line at all. Its top line, and the one the
    # reconciler (openinfo_reconcile) already serves as bank revenue, is total
    # interest income — «Всего процентные доходы» on the Excel form, «Итого
    # процентных доходов» in the structured JSON. A second-tier key: consulted
    # only when "revenue" itself finds nothing, so no commercial form can reach it.
    "revenue_bank": ["всего процентные доходы", "всего процентных доходов",
                     "итого процентных доходов", "итого процентные доходы"],
    # The bank income statement has no «валовая прибыль» or «прибыль от основной
    # деятельности» either, but it files the same tiers under its own names:
    #   «6. ЧИСТЫЙ ДОХОД ДО ОПЕРАЦИОННЫХ РАСХОДОВ»   — income after funding
    #     costs, before running costs: the gross-profit tier;
    #   «9. ЧИСТАЯ ПРИБЫЛЬ ДО УПЛАТЫ НАЛОГОВ …»      — line 6 less operating
    #     expenses and non-credit losses: the operating-result tier.
    # So the derived «операционные расходы» (gross − operating) reproduces the
    # form's own «з. Итого операционных расходов» exactly when line 8 is nought
    # (HMKB 2022: 1 735 075 932 − 903 084 643 = 831 991 289, the filed line 7з).
    # Second-tier keys like revenue_bank: consulted only when the commercial
    # patterns found nothing, so no jsc/insurance form can reach them.
    "gross_profit_bank": ["чистый доход до операционных расходов",
                          "чистые доходы до операционных расходов"],
    "operating_income_bank": ["чистая прибыль до уплаты налогов",
                              "чистая прибыль (убытки) до уплаты налогов"],
}


# Labels a key's patterns match but must NOT accept. The bank income statement
# publishes THREE lines the net-profit patterns match, in this order:
#   «6. ЧИСТЫЙ ДОХОД ДО ОПЕРАЦИОННЫХ РАСХОДОВ»       (an aggregate, 2.2× the bottom line)
#   «9. ЧИСТАЯ ПРИБЫЛЬ ДО УПЛАТЫ НАЛОГОВ И ДРУГИХ ПОПРАВОК»
#   «11. ЧИСТАЯ ПРИБЫЛЬ (УБЫТКИ)»                     (the actual result)
# First-match took line 6, so EVERY bank showed net profit equal to the feed's
# revenue indicator (which openinfo builds from the same line 6) on every filed
# year — measured 2026-08-09: 12 banks, all years since 2016. The reconciler
# already takes the LAST «чистая прибыль» row; this brings the Excel parse to
# the same answer by refusing the intermediate lines instead of reordering.
_LABEL_EXCLUSIONS: dict[str, list[str]] = {
    "net_income": ["до операционных", "до уплаты", "до налогообложения",
                   "до введения", "до оценки", "before tax", "qadar"],
}


def _row_value(nums: list, strict_period: bool = False) -> float | None:
    """Pick the reporting-period amount from a parsed row's numeric cells.

    Several NSBU Excel layouts occur in the wild, but they all lay their period
    columns out OLDEST → NEWEST left-to-right, exactly as openinfo exports them:
      * bank/vertical forms → ``[amount]`` (single period; the line number lives
        in the label) or ``[prior, current]`` (begin-of-year | end-of-period);
      * commercial form №1 (balance) → ``[line_code, begin, end]``
        (header: «На начало отчётного периода» | «На конец отчётного периода»);
      * commercial form №2 (fin. results) → ``[line_code, prev_income,
        prev_expense, cur_income, cur_expense]``
        (header: «За соответствующий период прошлого года» | «За отчётный период»).

    The reporting-period figure is therefore the LATER column-group, never the
    first. A naive "first numeric after the code" grab returns last year's / the
    opening balance — the exact off-by-one-period bug this guards against.

    We drop a leading cell that is clearly a line code (a small integer, either
    dwarfed >100× by the value after it or sitting ahead of ≥2 more cells), then,
    when the remaining cells split into two equal period halves, read the first
    non-zero amount from the SECOND (reporting) half. We fall back to the first
    half only when the reporting half is entirely zero (e.g. a period that has
    not been reported yet).
    """
    vals: list[float] = []
    for n in nums:
        try:
            f = float(n)
        except (TypeError, ValueError):
            continue
        if f != f:  # NaN (blank cell captured as NaN) — skip so it can't shift the split
            continue
        vals.append(f)
    if not vals:
        return None
    # Detect a leading NSBU line-code cell (010, 030, 320 …): a small integer.
    # In the multi-column commercial layout (code + period pairs) the first cell
    # is ALWAYS the code, so drop it even when the amounts are zero (e.g. a fund
    # with no revenue → [10,0,0,0,0], must not return "10"). In a 2-cell layout
    # it's ambiguous, so only drop when the code is dwarfed by the value after it.
    first_is_code = (
        len(vals) >= 2
        and vals[0].is_integer()
        and 0 < vals[0] < 10000
        and (len(vals) >= 3 or abs(vals[1]) > abs(vals[0]) * 100)
    )
    rest = vals[1:] if first_is_code else vals

    def _first_nonzero(seq: list[float]) -> float | None:
        for v in seq:
            if abs(v) > 0.0001:
                return v
        return None

    def _half_value(half: list[float]) -> float | None:
        # A 2-cell half in the commercial form №2 layout is an income|expense
        # COLUMN PAIR, not two candidate values: a loss sits as a positive
        # number in the expense column. Reading "first non-zero" there returns
        # a loss with a plus sign — so read the pair as income − expense.
        if len(half) == 2:
            income, expense = half
            if abs(income) <= 0.0001 and abs(expense) <= 0.0001:
                return None
            return income - expense
        return _first_nonzero(half)

    # Period columns run oldest → newest, so the reporting period is the second
    # half of the value cells (form №2 prior|current income/expense pairs; form №1
    # and bank forms begin|end / prior|current). Prefer it; fall back if it's zero.
    if len(rest) >= 2 and len(rest) % 2 == 0:
        reporting = _half_value(rest[len(rest) // 2:])
        if reporting is not None:
            return reporting
        # A single balance ACCOUNT can legitimately end the period at zero — a
        # settlement account emptied, a loan repaid — and there the fallback would
        # publish the OPENING balance as the closing one. Only a total is safe to
        # fall back on, so the caller says which it is asking for.
        if strict_period:
            return 0.0
        return _half_value(rest[:len(rest) // 2])
    return _first_nonzero(rest)


def _extract_metric(rows: list[dict], key: str, strict_period: bool = False) -> float | None:
    patterns = _LABEL_PATTERNS.get(key, [])
    excludes = _LABEL_EXCLUSIONS.get(key, ())
    for row in rows:
        label = str(row.get("label") or "").lower()
        if any(p in label for p in patterns):
            if any(x in label for x in excludes):
                continue
            v = _row_value(row.get("numeric_values") or [], strict_period=strict_period)
            if v is not None:
                return v
    return None


def _squash(label: Any) -> str:
    return re.sub(r"\s+", "", str(label or "").lower().replace("ё", "е"))


# The obligations subtotal of the NSBU balance, by the line numbers it sums —
# «ИТОГО ПО II РАЗДЕЛУ (стр. 490+600)» on the jsc form, «Итого по разделу III
# (стр. 730 + 930)» on the insurance one. Matched on the formula and not on the
# wording because the asset side of both forms prints «ИТОГО ПО РАЗДЕЛУ II» too.
_LIABILITIES_SECTION_FORMULAS = ("490+600", "730+930")


def _extract_liabilities_total(rows: list[dict]) -> float | None:
    """The obligations total the issuer itself published, if the form prints one.

    Preferred over re-adding «Долгосрочные обязательства, всего» and «Текущие
    обязательства, всего»: where the two disagree it is the published total that
    satisfies assets = equity + liabilities, because an unfilled or stale part
    cell is what the parts carry (KVTS 2026Q2, MIQE 2026Q2, Uzum Sarmoya 2026Q2 —
    the last of which had NO obligations at all on the board).
    """
    for row in rows:
        squashed = _squash(row.get("label"))
        if "итого" in squashed and any(f in squashed for f in _LIABILITIES_SECTION_FORMULAS):
            v = _row_value(row.get("numeric_values") or [])
            if v is not None:
                return v
    return None


# The accounts «Денежные средства, всего» sums: the till, the settlement account,
# the FX accounts and the equivalents. Used to tell an account that really is
# empty from a filing that never broke the roll-up down.
_CASH_ACCOUNT_CODES = ("(5000)", "(5100)", "(5200)", "(5500")


def _extract_cash(rows: list[dict]) -> float | None:
    """«Наличность в кассе» — the settlement account (5100), where it is filled in.

    A zero on стр.5100 beside a non-zero sibling account is a real balance: the
    company ended the period with its operating account empty and its money in
    foreign currency or in equivalents. A zero beside siblings that are ALL zero,
    under a non-zero roll-up, is an issuer who filed only the total (AGMK 2026 Q2:
    «Денежные средства, всего» 688 238 787, every account under it at nought) —
    there is no 5100 figure in that filing, so the roll-up stands in. The bank
    form, which has no settlement-account line at all, always takes that path.
    """
    account = _extract_metric(rows, "cash_account", strict_period=True)
    if account:
        return account
    patterns = _LABEL_PATTERNS["cash_account"]
    others = [r for r in rows
              if not any(p in str(r.get("label") or "").lower() for p in patterns)]
    if account is not None:
        siblings = [_row_value(r.get("numeric_values") or [], strict_period=True)
                    for r in others
                    if any(c in str(r.get("label") or "") for c in _CASH_ACCOUNT_CODES)]
        if any(siblings):
            return account  # the breakdown is filled in; the account is simply empty
    # The roll-up (or, on the bank form, its own cash line) — never the settlement
    # account's own opening balance, which is why it is looked up without that row.
    roll_up = _extract_metric(others, "cash")
    return roll_up if roll_up is not None else account


def _gather_rows(excel_data: dict | None) -> list[dict]:
    if not excel_data:
        return []
    rows: list[dict] = []
    for sheet in (excel_data.get("sheets") or []):
        rows.extend(sheet.get("table_rows") or [])
    return rows


def compute_financial_ratios(income_data: dict | None, balance_data: dict | None) -> dict[str, Any]:
    income_rows = _gather_rows(income_data)
    balance_rows = _gather_rows(balance_data)
    all_rows = income_rows + balance_rows

    revenue = _extract_metric(income_rows or all_rows, "revenue")
    if revenue is None:
        # Bank form: no «выручка» line exists — total interest income is the
        # top line, exactly the figure the reconciler serves as bank revenue.
        revenue = _extract_metric(income_rows or all_rows, "revenue_bank")
    net_income = _extract_metric(income_rows or all_rows, "net_income")
    gross_profit = _extract_metric(income_rows or all_rows, "gross_profit")
    operating_income = _extract_metric(income_rows or all_rows, "operating_income")
    if gross_profit is None:
        gross_profit = _extract_metric(income_rows or all_rows, "gross_profit_bank")
    if operating_income is None:
        operating_income = _extract_metric(income_rows or all_rows, "operating_income_bank")
    total_assets = _extract_metric(balance_rows or all_rows, "total_assets")
    equity = _extract_metric(balance_rows or all_rows, "equity")
    total_liabilities = _extract_metric(balance_rows or all_rows, "total_liabilities")
    if total_liabilities is None:
        total_liabilities = _extract_liabilities_total(balance_rows or all_rows)
    if total_liabilities is None:
        lt = _extract_metric(balance_rows or all_rows, "lt_liabilities")
        cur = _extract_metric(balance_rows or all_rows, "cur_liabilities")
        if lt is not None or cur is not None:
            total_liabilities = (lt or 0.0) + (cur or 0.0)
    # Commercial form №1 labels its equity total only "Итого по разделу I" — the
    # same words as the assets-section total, so no label pattern can pick it out.
    # On a published balance the identity assets = equity + liabilities holds, so
    # take equity as the difference instead.
    if equity is None and total_assets is not None and total_liabilities is not None:
        equity = total_assets - total_liabilities
    cash = _extract_cash(balance_rows or all_rows)

    def _safe_ratio(num: float | None, den: float | None) -> float | None:
        if num is None or den is None or den == 0:
            return None
        return round(num / den * 100, 2)

    def _safe_div(num: float | None, den: float | None) -> float | None:
        if num is None or den is None or den == 0:
            return None
        return round(num / den, 4)

    metrics: dict[str, Any] = {
        "ROA": _safe_ratio(net_income, total_assets),
        "ROE": _safe_ratio(net_income, equity),
        "net_margin": _safe_ratio(net_income, revenue),
        "debt_ratio": _safe_ratio(total_liabilities, total_assets),
        "debt_to_equity": _safe_div(total_liabilities, equity),
    }

    source_rows: dict[str, Any] = {
        "revenue": revenue,
        "net_income": net_income,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "cash": cash,
        "total_assets": total_assets,
        "equity": equity,
        "total_liabilities": total_liabilities,
    }

    return {"metrics": metrics, "source_values": source_rows}


def get_company_reports(ticker: str) -> list[dict[str, Any]]:
    """Return all catalog reports for the issuer behind a ticker, newest first.

    By the issuer, not the ticker: the company page and /catalog are looking at
    the same record, and reading it per-ticker made them disagree — 28 filings
    on one page and 38 on the other for the same bank, because ten had been
    synced under its preferred class.
    """
    conn = get_catalog_conn()
    siblings = _org_siblings(conn, ticker) or [(ticker or "").upper()]
    placeholders = ",".join("?" * len(siblings))
    rows = conn.execute(f"""
        SELECT report_form, period_type, year, quarter, title, pdf_url, excel_url, excel_url_form1, synced_at
        FROM catalog_reports
        WHERE ticker IN ({placeholders})
        ORDER BY year DESC, quarter DESC, synced_at DESC
    """, siblings).fetchall()
    conn.close()
    best: dict[tuple, tuple[int, dict[str, Any]]] = {}
    for r in rows:
        key = _report_key(r)
        links = sum(1 for c in ("pdf_url", "excel_url", "excel_url_form1") if r[c])
        if key not in best or links > best[key][0]:
            best[key] = (links, dict(r))
    return [r for _, r in best.values()]


def get_company_ratios_cached(ticker: str) -> dict[str, Any]:
    """Return most recent cached ratios for a ticker."""
    conn = get_catalog_conn()
    # Same period ranking as get_all_financials / _period_key: an annual is stored
    # with quarter = 0 but ranks as the year's FINAL figure, so plain
    # "ORDER BY quarter DESC" handed Q1 the win over its own completed annual.
    row = conn.execute("""
        SELECT year, quarter, form, roa, roe, net_margin, debt_ratio, debt_to_equity, updated_at
        FROM catalog_ratios
        WHERE ticker = ?
          AND quarter BETWEEN 0 AND 4
          AND NOT (quarter = 0 AND year > ?)
        ORDER BY year DESC,
                 CASE WHEN quarter = 0 THEN 5 ELSE quarter END DESC,
                 updated_at DESC
        LIMIT 1
    """, (ticker, _latest_complete_fiscal_year())).fetchone()
    conn.close()
    if not row:
        return {}
    metrics = {}
    if row["roa"] is not None:
        metrics["ROA"] = row["roa"]
    if row["roe"] is not None:
        metrics["ROE"] = row["roe"]
    if row["net_margin"] is not None:
        metrics["net_margin"] = row["net_margin"]
    if row["debt_ratio"] is not None:
        metrics["debt_ratio"] = row["debt_ratio"]
    if row["debt_to_equity"] is not None:
        metrics["debt_to_equity"] = row["debt_to_equity"]
    # Book equity for P/B. catalog_ratios stores only the coefficients, so this
    # comes from the same fact-store logic the market-wide endpoint uses — the
    # company page previously had no equity feed at all and fell back to the
    # P/E x ROE identity, which is undefined for loss-makers and therefore
    # disagreed with the market table on exactly those issuers.
    return {
        "year": row["year"], "quarter": row["quarter"], "form": row["form"],
        "metrics": metrics,
        "total_equity": _company_equity(ticker),
    }


def _company_equity(ticker: str) -> float | None:
    """Latest book equity for one ticker, in full UZS.

    Deliberately reuses :func:`get_all_ratios` rather than re-deriving equity from
    a narrower query: the derivation (published figure, else the balance identity,
    else the ROE identity, all per-period) is subtle, and a second copy of it is
    how the P/E–P/B divergence happened in the first place. The result is memoized
    so a per-company call does not repeat the scan.
    """
    try:
        entry = _ratios_cached().get(str(ticker or "").upper()) or {}
    except Exception:
        logger.exception("equity lookup failed for %s", ticker)
        return None
    equity = entry.get("total_equity")
    if not isinstance(equity, (int, float)):
        return None
    return float(equity) * NSBU_THOUSANDS_UZS


# Short-lived memo over the fact-store ratio scan. The underlying facts change
# only when a collector pushes, so seconds of staleness is invisible, while the
# scan itself runs on every market load and every company page.
_RATIOS_CACHE_TTL_SECONDS = int(os.getenv("RATIOS_CACHE_TTL_SECONDS", "60"))
_ratios_cache: tuple[float, dict[str, dict[str, Any]]] | None = None
_ratios_cache_lock = threading.Lock()


def _ratios_cached() -> dict[str, dict[str, Any]]:
    global _ratios_cache
    now = time.monotonic()
    with _ratios_cache_lock:
        if _ratios_cache is not None and now - _ratios_cache[0] < _RATIOS_CACHE_TTL_SECONDS:
            return _ratios_cache[1]
    fresh = get_all_ratios()
    with _ratios_cache_lock:
        _ratios_cache = (now, fresh)
    return fresh


def invalidate_ratios_cache() -> None:
    """Drop the memo — called after any write that changes the fact store."""
    global _ratios_cache
    with _ratios_cache_lock:
        _ratios_cache = None


# ---------------------------------------------------------------------------
# Dynamics time series
# ---------------------------------------------------------------------------

def build_dynamics_data(ticker: str, form: str = "NSBU") -> dict[str, Any]:
    conn = get_catalog_conn()
    annual_rows = conn.execute(
        """
        SELECT year, excel_url, excel_url_form1
        FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND period_type = 'annual' AND year IS NOT NULL
          AND year <= ?
        ORDER BY year ASC
        """,
        (ticker, form, _latest_complete_fiscal_year()),
    ).fetchall()
    conn.close()

    if not annual_rows:
        return {"ticker": ticker, "form": form, "years": [], "series": {}}

    session = _make_session()
    years: list[int] = []
    series: dict[str, list[float | None]] = {
        "revenue": [],
        "net_income": [],
        "total_assets": [],
        "equity": [],
        "total_liabilities": [],
    }

    for row in annual_rows:
        yr = row["year"]
        years.append(yr)

        income_data: dict | None = None
        balance_data: dict | None = None

        if row["excel_url"]:
            doc = {"excel_url": row["excel_url"], "id": None, "object_id": None,
                   "published_at": None, "period_type": "annual", "report_form": form, "title": None}
            try:
                p = parse_excel_report_document(session, doc)
                if p.get("ok"):
                    income_data = p
            except Exception:
                pass

        if row["excel_url_form1"]:
            doc1 = {"excel_url": row["excel_url_form1"], "id": None, "object_id": None,
                    "published_at": None, "period_type": "annual", "report_form": form, "title": None}
            try:
                p1 = parse_excel_report_document(session, doc1)
                if p1.get("ok"):
                    balance_data = p1
            except Exception:
                pass

        ratios = compute_financial_ratios(income_data, balance_data)
        vals = ratios.get("source_values") or {}
        for key in series:
            series[key].append(vals.get(key))

    # --- Quarterly series (last 8 quarters) ----------------------------------
    conn2 = get_catalog_conn()
    quarter_rows = conn2.execute(
        """
        SELECT year, quarter, excel_url, excel_url_form1
        FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND period_type = 'quarter'
          AND year IS NOT NULL AND quarter > 0
        ORDER BY year DESC, quarter DESC
        LIMIT 16
        """,
        (ticker, form),
    ).fetchall()
    conn2.close()

    quarterly: list[dict[str, Any]] = []
    metric_keys = ["revenue", "net_income", "total_assets", "equity", "total_liabilities"]
    for qrow in reversed(quarter_rows):
        yr, q = qrow["year"], qrow["quarter"]
        inc, bal = None, None
        if qrow["excel_url"]:
            doc = {"excel_url": qrow["excel_url"], "id": None, "object_id": None,
                   "published_at": None, "period_type": "quarter", "report_form": form, "title": None}
            try:
                p = parse_excel_report_document(session, doc)
                if p.get("ok"):
                    inc = p
            except Exception:
                pass
        if qrow["excel_url_form1"]:
            doc1 = {"excel_url": qrow["excel_url_form1"], "id": None, "object_id": None,
                    "published_at": None, "period_type": "quarter", "report_form": form, "title": None}
            try:
                p1 = parse_excel_report_document(session, doc1)
                if p1.get("ok"):
                    bal = p1
            except Exception:
                pass
        vals_q = (compute_financial_ratios(inc, bal).get("source_values") or {})
        entry: dict[str, Any] = {"label": f"Q{q} {yr}", "year": yr, "quarter": q}
        for k in metric_keys:
            entry[k] = vals_q.get(k)
        quarterly.append(entry)

    # --- De-cumulate flow metrics -------------------------------------------
    # NSBU quarterly form-2 figures are cumulative year-to-date (an H1 filing's
    # "revenue" is six months of revenue). Serving them per-quarter labeled
    # "Q2" overstated quarters and made seasonality structurally meaningless.
    # Derive true standalone quarters by differencing consecutive YTD values of
    # the same year; a quarter without its predecessor on file stays None (the
    # cumulative figure is still exposed as <metric>_ytd). Balance-sheet
    # metrics (assets/equity/liabilities) are point-in-time and stay as-is.
    flow_keys = ("revenue", "net_income")
    for e in quarterly:
        for k in flow_keys:
            e[f"{k}_ytd"] = e.get(k)
    ytd_by_period = {(e["year"], e["quarter"]): e for e in quarterly}
    for e in quarterly:
        for k in flow_keys:
            ytd = e.get(f"{k}_ytd")
            if not isinstance(ytd, (int, float)):
                e[k] = None
                continue
            if e["quarter"] <= 1:
                continue  # Q1 cumulative == standalone
            prev = ytd_by_period.get((e["year"], e["quarter"] - 1))
            prev_ytd = prev.get(f"{k}_ytd") if prev else None
            e[k] = round(ytd - prev_ytd, 2) if isinstance(prev_ytd, (int, float)) else None

    # --- Seasonality (ТЗ §3.5): average a headline metric by quarter across years.
    # Uses the de-cumulated standalone quarters computed above — averaging raw
    # YTD values would always rank Q3 "above" Q1 regardless of real seasonality.
    # Needs ≥3 years of history; otherwise flagged insufficient rather than shown.
    season_metric = "revenue"
    by_q: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    years_seen: set[int] = set()
    for e in quarterly:
        v = e.get(season_metric)
        q = e.get("quarter")
        if isinstance(v, (int, float)) and q in by_q:
            by_q[q].append(float(v))
            years_seen.add(e.get("year"))
    seasonality = {
        "metric": season_metric,
        "years_covered": len(years_seen),
        "insufficient": len(years_seen) < 3,
        "quarter_avg": {q: (round(sum(vals) / len(vals), 2) if vals else None) for q, vals in by_q.items()},
    }

    return {"ticker": ticker, "form": form, "years": years, "series": series,
            "quarterly": quarterly, "seasonality": seasonality}
