"""provenance.py — where every published number came from.

ТЗ Дополнение 1, часть Б. The reporting catalog is a shelf of links today: it
lists companies and opens PDFs on openinfo.uz, and hands nothing to the rest of
the system. Three consequences, all of them visible:

The screen contradicts itself. The header says 85 companies and 2 021 reports;
the list returns 73 rows holding 1 659. Twelve companies and 362 reports exist
in the database and in nobody's view, because the two numbers come from separate
queries that are never compared. **So the counters and the list are now produced
by ONE call** — a disagreement becomes impossible rather than unnoticed.

It is keyed by ticker, not by issuer. 73 rows are 66 organisations: one issuer
has four bond series, another four, another two. Their statements are shared but
either duplicated across rows or shown nowhere — five series display "0 reports"
while their issuer's filings sit under another ticker.

And the part this module exists for: **no published figure names the report it
came from.** "Where did UQEQ's revenue of 31 379 733 363 530 — 131 times its
annual — come from?" is currently unanswerable: nobody can say which filing,
which form, which period, or whether it was parsed at all rather than read off
the wrong field. That gap is the origin of the entire FIN defect group.

A report therefore moves through explicit states and numbers are published only
from `validated`. A rejected report is not deleted: "we have the report and
could not parse it" is information, and an empty space is not.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

# ТЗ Б.3. Numbers are published from `validated` and never straight from
# `parsed` — parsing is extraction, validation is the decision to believe it.
STATES = ("discovered", "downloaded", "parsed", "validated", "published",
          "download_failed", "parse_failed", "rejected", "stale")
PUBLISHABLE = ("validated", "published")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or _conn()
    try:
        import dbx

        dbx.ensure_schema(conn, "provenance", _create_schema)
    finally:
        if own:
            conn.close()


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS issuers (
              org_id    TEXT PRIMARY KEY,
              name      TEXT NOT NULL,
              inn       TEXT,
              logo_url  TEXT,
              synced_at TEXT
            );
            CREATE TABLE IF NOT EXISTS source_reports (
              id            INTEGER PRIMARY KEY AUTOINCREMENT,
              org_id        TEXT NOT NULL,
              report_form   TEXT NOT NULL,
              period_type   TEXT NOT NULL,
              period_year   INTEGER NOT NULL,
              period_quarter INTEGER,
              title         TEXT,
              pdf_url       TEXT, excel_url TEXT,
              file_hash     TEXT,
              state         TEXT NOT NULL DEFAULT 'discovered',
              state_reason  TEXT,
              discovered_at TEXT NOT NULL,
              parsed_at     TEXT, published_at TEXT,
              UNIQUE (org_id, report_form, period_type, period_year, period_quarter)
            );
            CREATE INDEX IF NOT EXISTS ix_reports_state
              ON source_reports (state, period_year DESC);
            CREATE TABLE IF NOT EXISTS report_figures (
              report_id  INTEGER NOT NULL REFERENCES source_reports(id),
              field      TEXT NOT NULL,
              value      REAL,
              unit_scale INTEGER NOT NULL DEFAULT 1,
              page       INTEGER,
              raw_label  TEXT,
              PRIMARY KEY (report_id, field)
            );
            CREATE TABLE IF NOT EXISTS bond_reference (
              ticker      TEXT PRIMARY KEY,
              isin        TEXT,
              nominal     REAL,
              currency    TEXT NOT NULL DEFAULT 'UZS',
              coupon_rate REAL,
              coupon_freq INTEGER,
              coupon_type TEXT,
              float_base  TEXT,
              -- «Har oyda» steps a calendar month, «Har 30 kunda» thirty days.
              coupon_basis TEXT,
              coupon_period_days INTEGER,
              issue_date  TEXT,
              maturity_date TEXT,
              issue_volume REAL,
              placed_volume REAL,
              issuer       TEXT,
              amortization INTEGER NOT NULL DEFAULT 0,
              has_put      INTEGER NOT NULL DEFAULT 0,
              has_call     INTEGER NOT NULL DEFAULT 0,
              -- Which source states the term: 'openinfo_facts' (the issuer
              -- filed it) or 'exchange_registry' (the register of circulating
              -- issues states the undertaking). A term never shows as filed
              -- when it is only registered.
              coupon_source   TEXT,
              maturity_source TEXT,
              source_url   TEXT,
              synced_at    TEXT
            );
            CREATE TABLE IF NOT EXISTS bond_coupons (
              ticker      TEXT NOT NULL REFERENCES bond_reference(ticker),
              coupon_no   INTEGER NOT NULL,
              -- The issuer files what a coupon pays and when payment opens, not
              -- the accrual period behind it (ТЗ Доп.1 §А.4 assumed a schedule
              -- from a reference nobody publishes). Demanding the period here
              -- would only have it invented, so it stays open.
              period_from TEXT, period_to TEXT,
              pay_date    TEXT NOT NULL,
              amount      REAL,
              is_paid     INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (ticker, coupon_no)
            );
            -- ГЦБ primary-market results from the Central Bank's fiscal-agent
            -- page — the base curve every corporate spread is measured against.
            -- Keyed by (sec_id, auction_date): a reopened line keeps its number
            -- but each placement is its own result.
            CREATE TABLE IF NOT EXISTS gov_bond_auctions (
              sec_id          TEXT NOT NULL,
              auction_date    TEXT NOT NULL,
              isin            TEXT,
              term_days       INTEGER,
              maturity_date   TEXT,
              income_type     TEXT,
              announced_volume REAL,
              dealers         INTEGER,
              placed_qty      REAL,
              placed_value    REAL,
              wavg_rate       REAL,
              min_rate        REAL,
              max_rate        REAL,
              source_url      TEXT,
              synced_at       TEXT,
              PRIMARY KEY (sec_id, auction_date)
            );
            CREATE INDEX IF NOT EXISTS ix_gov_auctions_date
              ON gov_bond_auctions (auction_date DESC);
            -- The key rate as the Central Bank's front page states it, one row
            -- per change — arrival-only history, never a hand-configured number.
            CREATE TABLE IF NOT EXISTS gov_key_rate (
              effective_from TEXT PRIMARY KEY,
              rate           REAL NOT NULL,
              source_url     TEXT,
              synced_at      TEXT
            );
            -- Commercial-bank exchange rates from bankxizmatlari.uz. Keyed on the
            -- BANK's own stated update time (bank_updated_at), not ours: a bank
            -- that has not moved its rate since the last poll re-states the same
            -- key and the upsert is a no-op, so history grows only when a bank
            -- actually changes something. When the source's own timestamp fails
            -- to parse, the collector falls back to its own fetch time so the
            -- key is never NULL (PostgreSQL rejects NULL in a primary key).
            CREATE TABLE IF NOT EXISTS bank_fx_rates (
              bank_code       TEXT NOT NULL,
              bank_name       TEXT,
              ccy             TEXT NOT NULL,
              channel         TEXT NOT NULL,
              buy             REAL,
              sell            REAL,
              flag            TEXT,
              bank_updated_at TEXT NOT NULL,
              source_url      TEXT,
              synced_at       TEXT,
              PRIMARY KEY (bank_code, ccy, channel, bank_updated_at)
            );
            CREATE INDEX IF NOT EXISTS ix_bank_fx_latest
              ON bank_fx_rates (ccy, channel, bank_updated_at DESC);
            """
    )
    conn.commit()


def file_hash(payload: bytes | str) -> str:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# The report state machine (ТЗ Б.3)
# ---------------------------------------------------------------------------

def upsert_report(org_id: str, report_form: str, period_type: str, period_year: int,
                  period_quarter: int | None = None, *, pdf_url: str | None = None,
                  excel_url: str | None = None, title: str | None = None,
                  hash_value: str | None = None) -> int:
    """Register a report, or return it to `discovered` if the source replaced it.

    The source is entitled to re-upload a filing, and that has to be caught
    rather than ignored: a changed file hash sends the report back to the start
    and it is parsed again.
    """
    init()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, file_hash, state FROM source_reports WHERE org_id=? AND report_form=? "
            "AND period_type=? AND period_year=? AND IFNULL(period_quarter,-1)=IFNULL(?,-1)",
            (org_id, report_form, period_type, period_year, period_quarter)).fetchone()
        if row is None:
            # RETURNING, not lastrowid: the latter is a SQLite attribute and
            # psycopg does not have it. RETURNING is standard and says exactly
            # which row was written even under concurrency.
            cur = conn.execute(
                "INSERT INTO source_reports (org_id, report_form, period_type, period_year, "
                "period_quarter, title, pdf_url, excel_url, file_hash, state, discovered_at) "
                "VALUES (?,?,?,?,?,?,?,?,?, 'discovered', ?) RETURNING id",
                (org_id, report_form, period_type, period_year, period_quarter, title,
                 pdf_url, excel_url, hash_value, _now()))
            new_id = int(cur.fetchone()[0])
            conn.commit()
            return new_id
        if hash_value and row["file_hash"] and hash_value != row["file_hash"]:
            conn.execute(
                "UPDATE source_reports SET file_hash=?, state='discovered', "
                "state_reason='файл в источнике заменён', parsed_at=NULL, published_at=NULL, "
                "pdf_url=COALESCE(?, pdf_url), excel_url=COALESCE(?, excel_url) WHERE id=?",
                (hash_value, pdf_url, excel_url, row["id"]))
        else:
            conn.execute(
                "UPDATE source_reports SET pdf_url=COALESCE(?, pdf_url), "
                "excel_url=COALESCE(?, excel_url), title=COALESCE(?, title), "
                "file_hash=COALESCE(?, file_hash) WHERE id=?",
                (pdf_url, excel_url, title, hash_value, row["id"]))
        conn.commit()
        return int(row["id"])
    finally:
        conn.close()


def set_state(report_id: int, state: str, reason: str | None = None) -> None:
    if state not in STATES:
        raise ValueError(f"unknown report state: {state}")
    conn = _conn()
    try:
        stamps = ""
        if state == "parsed":
            stamps = ", parsed_at = '%s'" % _now()
        elif state == "published":
            stamps = ", published_at = '%s'" % _now()
        conn.execute(f"UPDATE source_reports SET state=?, state_reason=?{stamps} WHERE id=?",
                     (state, reason, report_id))
        conn.commit()
    finally:
        conn.close()


def report_index() -> dict[tuple, int]:
    """Every registered report keyed the way `report_id_for` resolves one.

    `report_id_for` opens a connection and runs a join per lookup, which is the
    right shape for one question and the wrong shape for a backfill asking it
    once per cached figure. One issuer's several tickers each get their own
    entry, because that is what the join in `report_id_for` produces.
    """
    init()
    conn = _conn()
    index: dict[tuple, int] = {}
    try:
        for row in conn.execute(
                "SELECT r.id, r.report_form, r.period_type, r.period_year, "
                "       r.period_quarter, "
                "       COALESCE(c.ticker, REPLACE(r.org_id,'ticker:','')) AS ticker "
                "FROM source_reports r "
                "LEFT JOIN catalog_companies c ON c.org_id = r.org_id"):
            key = (str(row["ticker"]), str(row["report_form"]), str(row["period_type"]),
                   int(row["period_year"]),
                   int(row["period_quarter"]) if row["period_quarter"] else -1)
            # `LIMIT 1` in the single-lookup form: the first match wins.
            index.setdefault(key, int(row["id"]))
    finally:
        conn.close()
    return index


def set_state_bulk(report_ids: Sequence[int], state: str,
                   reason: str | None = None) -> int:
    """`set_state` for many reports over one connection."""
    if state not in STATES:
        raise ValueError(f"unknown report state: {state}")
    ids = [int(i) for i in report_ids or []]
    if not ids:
        return 0
    conn = _conn()
    try:
        stamps = ""
        if state == "parsed":
            stamps = ", parsed_at = '%s'" % _now()
        elif state == "published":
            stamps = ", published_at = '%s'" % _now()
        conn.executemany(
            f"UPDATE source_reports SET state=?, state_reason=?{stamps} WHERE id=?",
            [(state, reason, report_id) for report_id in ids])
        conn.commit()
    finally:
        conn.close()
    return len(ids)


def record_figures_bulk(items: Iterable[tuple[int, Iterable[dict[str, Any]]]]) -> int:
    """`record_figures` for many reports over one connection.

    Deduplicated on (report_id, field), last write winning — the same order the
    one-at-a-time upserts resolved in. Two tickers of one issuer resolve to one
    report, so the pair genuinely repeats within a single backfill, and
    PostgreSQL refuses an ON CONFLICT batch that would touch a row twice.
    """
    by_target: dict[tuple[int, str], tuple] = {}
    for report_id, figures in items or []:
        for figure in figures or []:
            field = str(figure.get("field") or "").strip()
            if not field:
                continue
            by_target[(int(report_id), field)] = (
                int(report_id), field, figure.get("value"),
                int(figure.get("unit_scale") or 1),
                figure.get("page"), figure.get("raw_label"))
    params = list(by_target.values())
    if not params:
        return 0
    conn = _conn()
    try:
        conn.executemany(
            "INSERT INTO report_figures (report_id, field, value, unit_scale, page, raw_label) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(report_id, field) DO UPDATE SET "
            "value=excluded.value, unit_scale=excluded.unit_scale, page=excluded.page, "
            "raw_label=excluded.raw_label",
            params)
        conn.commit()
    finally:
        conn.close()
    return len(params)


def record_figures(report_id: int, figures: Iterable[dict[str, Any]]) -> int:
    """Store extracted numbers WITH the page and the label they came from.

    That pair is the traceability: a reader sees not only the figure but the
    line of the report the parser took it from, which is what turns "your
    revenue is wrong" from a day's argument into a minute's check.
    """
    conn = _conn()
    written = 0
    try:
        for figure in figures or []:
            field = str(figure.get("field") or "").strip()
            if not field:
                continue
            conn.execute(
                "INSERT INTO report_figures (report_id, field, value, unit_scale, page, raw_label) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(report_id, field) DO UPDATE SET "
                "value=excluded.value, unit_scale=excluded.unit_scale, page=excluded.page, "
                "raw_label=excluded.raw_label",
                (report_id, field, figure.get("value"), int(figure.get("unit_scale") or 1),
                 figure.get("page"), figure.get("raw_label")))
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def report(report_id: int) -> dict[str, Any] | None:
    init()
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM source_reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            return None
        figures = [dict(f) for f in conn.execute(
            "SELECT field, value, unit_scale, page, raw_label FROM report_figures "
            "WHERE report_id=?", (report_id,))]
        out = dict(row)
        out["figures"] = figures
        # ТЗ Б.5: the reverse question. A rejected report with used_by false is
        # normal; a rejected report with used_by true is an incident.
        out["used_by"] = {"financials": row["state"] in PUBLISHABLE and bool(figures)}
        return out
    finally:
        conn.close()


def summary(now: datetime | None = None) -> dict[str, Any]:
    """Counters AND the issuer list from ONE query (ТЗ Б.5).

    The header said 85 companies and the list returned 73 because they were two
    queries nobody compared. Reading both from the same statement makes them
    unable to disagree.
    """
    init()
    conn = _conn()
    try:
        by_state = {r["state"]: r["n"] for r in conn.execute(
            "SELECT state, COUNT(*) AS n FROM source_reports GROUP BY state")}
        by_form = {r["report_form"]: r["n"] for r in conn.execute(
            "SELECT report_form, COUNT(*) AS n FROM source_reports GROUP BY report_form")}
        issuers = [dict(r) for r in conn.execute(
            "SELECT i.org_id, i.name, i.synced_at, COUNT(r.id) AS reports, "
            "SUM(CASE WHEN r.state IN ('validated','published') THEN 1 ELSE 0 END) AS published, "
            "SUM(CASE WHEN r.state IN ('rejected','parse_failed','download_failed') "
            "         THEN 1 ELSE 0 END) AS failed, "
            "SUM(CASE WHEN r.state = 'discovered' THEN 1 ELSE 0 END) AS pending "
            "FROM issuers i LEFT JOIN source_reports r ON r.org_id = i.org_id "
            "GROUP BY i.org_id, i.name, i.synced_at ORDER BY i.name")]
        # ТЗ Б.6: an issuer's SECURITIES hang off the issuer, bond series
        # included. Listing by ticker is what made five series show "0 отчётов"
        # while their issuer's filings sat under another ticker.
        tickers: dict[str, list[str]] = {}
        for row in conn.execute(
                "SELECT org_id, ticker FROM catalog_companies "
                "WHERE org_id IS NOT NULL AND org_id != '' ORDER BY ticker"):
            tickers.setdefault(row["org_id"], []).append(row["ticker"])
        for issuer in issuers:
            issuer["tickers"] = tickers.get(issuer["org_id"], [])
        last_sync = conn.execute("SELECT MAX(synced_at) AS s FROM issuers").fetchone()["s"]
    finally:
        conn.close()

    total = sum(by_state.values())
    reference = now or datetime.now(timezone.utc)
    staleness_hours = None
    if last_sync:
        try:
            stamp = datetime.fromisoformat(last_sync)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            staleness_hours = (reference - stamp).total_seconds() / 3600.0
        except ValueError:
            staleness_hours = None
    limit = 24.0
    try:
        from formulas import thresholds

        limit = float(thresholds()["catalog"].get("staleness_warn_hours", 24))
    except Exception:  # noqa: BLE001 — a missing config must not hide staleness
        pass
    return {
        # These two are computed from the same rows, so they cannot disagree.
        "issuers": len(issuers),
        "reports_total": total,
        "by_state": by_state,
        "by_form": by_form,
        "items": issuers,
        "last_sync": last_sync,
        "staleness_hours": staleness_hours,
        # ТЗ Б.6: age is a sentence in the interface, not a date the reader has
        # to subtract from today. The catalog was ten days behind the market and
        # the screen showed only a date.
        "staleness_warn_hours": limit,
        "is_stale": bool(staleness_hours and staleness_hours > limit),
    }


def queue(limit: int = 200) -> list[dict[str, Any]]:
    """Reports that failed to parse — a work queue, not a shelf (ТЗ Б.5)."""
    init()
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM source_reports WHERE state IN "
            "('discovered','downloaded','parse_failed','download_failed','rejected') "
            "ORDER BY period_year DESC, id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bond reference (ТЗ А.4)
# ---------------------------------------------------------------------------

def upsert_bond_reference(rows: Sequence[dict[str, Any]]) -> int:
    init()
    conn = _conn()
    fields = ("ticker", "isin", "nominal", "currency", "coupon_rate", "coupon_freq",
              "coupon_type", "float_base", "coupon_basis", "coupon_period_days",
              "issue_date", "maturity_date", "issue_volume",
              "placed_volume", "issuer", "coupon_source", "maturity_source",
              "amortization", "has_put", "has_call", "source_url")
    written = 0
    try:
        for row in rows or []:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker:
                continue
            # Defaults for the columns the schema requires: a partial reference
            # is the normal state of this table, not an error.
            defaults = {"currency": "UZS", "amortization": 0, "has_put": 0, "has_call": 0}
            values = [ticker] + [row.get(f, defaults.get(f)) if row.get(f) is not None
                                 else defaults.get(f) for f in fields[1:]] + [_now()]
            placeholders = ",".join("?" * (len(fields) + 1))
            # COALESCE, not overwrite: a filed fact never un-files, so a term is
            # arrival-only. The walk reads a WINDOW of each issuer's filings, and
            # the run where an old issue slides out of it must not erase the
            # coupon and maturity a previous run already proved.
            updates = ",".join(f"{f}=COALESCE(excluded.{f}, bond_reference.{f})"
                               for f in fields[1:]) + ", synced_at=excluded.synced_at"
            conn.execute(
                f"INSERT INTO bond_reference ({','.join(fields)}, synced_at) "
                f"VALUES ({placeholders}) ON CONFLICT(ticker) DO UPDATE SET {updates}", values)
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def upsert_bond_coupons(rows: Sequence[dict[str, Any]]) -> int:
    """The coupons an issuer has actually filed, replacing that issue's set.

    Rewritten per ticker rather than merged: the filings ARE the schedule, so a
    coupon that vanished from the source has to vanish here too — a merge would
    keep a payment the issuer withdrew.
    """
    init()
    conn = _conn()
    fields = ("ticker", "coupon_no", "period_from", "period_to", "pay_date", "amount", "is_paid")
    written = 0
    try:
        for ticker in {str(r.get("ticker") or "").upper() for r in rows or [] if r.get("ticker")}:
            conn.execute("DELETE FROM bond_coupons WHERE ticker = ?", (ticker,))
        for row in rows or []:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker or not row.get("pay_date"):
                continue
            values = [ticker] + [row.get(f) for f in fields[1:]]
            conn.execute(
                f"INSERT INTO bond_coupons ({','.join(fields)}) "
                f"VALUES ({','.join('?' * len(fields))})", values)
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def bond_references() -> dict[str, dict[str, Any]]:
    init()
    conn = _conn()
    try:
        return {r["ticker"]: dict(r) for r in conn.execute("SELECT * FROM bond_reference")}
    finally:
        conn.close()


def bond_coupons() -> dict[str, list[dict[str, Any]]]:
    init()
    conn = _conn()
    try:
        out: dict[str, list[dict[str, Any]]] = {}
        for row in conn.execute("SELECT * FROM bond_coupons ORDER BY ticker, coupon_no"):
            out.setdefault(row["ticker"], []).append(dict(row))
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ГЦБ auctions + key rate — the base curve of the UZS market
# ---------------------------------------------------------------------------

def upsert_gov_auctions(rows: Sequence[dict[str, Any]]) -> int:
    """Auction results are final the day they are published: a plain overwrite,
    no COALESCE — re-reading the page can only restate the same protocol."""
    init()
    conn = _conn()
    fields = ("sec_id", "auction_date", "isin", "term_days", "maturity_date",
              "income_type", "announced_volume", "dealers", "placed_qty",
              "placed_value", "wavg_rate", "min_rate", "max_rate", "source_url")
    updates = ",".join(f"{f}=excluded.{f}" for f in fields[2:]) + ", synced_at=excluded.synced_at"
    written = 0
    try:
        for row in rows or []:
            sec_id = str(row.get("sec_id") or "").strip().upper()
            day = str(row.get("auction_date") or "").strip()
            if not sec_id or not day:
                continue
            values = [sec_id, day] + [row.get(f) for f in fields[2:]] + [_now()]
            conn.execute(
                f"INSERT INTO gov_bond_auctions ({','.join(fields)}, synced_at) "
                f"VALUES ({','.join('?' * (len(fields) + 1))}) "
                f"ON CONFLICT(sec_id, auction_date) DO UPDATE SET {updates}", values)
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def upsert_key_rate(row: dict[str, Any] | None) -> int:
    init()
    if not row or row.get("rate") is None or not row.get("effective_from"):
        return 0
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO gov_key_rate (effective_from, rate, source_url, synced_at) "
            "VALUES (?,?,?,?) ON CONFLICT(effective_from) DO UPDATE SET "
            "rate=excluded.rate, source_url=excluded.source_url, synced_at=excluded.synced_at",
            (str(row["effective_from"]), float(row["rate"]), row.get("source_url"), _now()))
        conn.commit()
    finally:
        conn.close()
    return 1


def gov_auctions() -> list[dict[str, Any]]:
    init()
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM gov_bond_auctions ORDER BY auction_date DESC, term_days")]
    finally:
        conn.close()


def key_rate() -> dict[str, Any] | None:
    """The latest key rate on record, with the date it took effect."""
    init()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM gov_key_rate ORDER BY effective_from DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Commercial-bank exchange rates (bankxizmatlari.uz)
# ---------------------------------------------------------------------------

def upsert_bank_fx_rates(rows: Sequence[dict[str, Any]]) -> int:
    """Upsert bank rate cells, keyed on each bank's OWN stated update time.

    A bank that has not moved a rate since the last poll republishes the same
    ``bank_updated_at``, so the conflict path fires and no new history row is
    created — a quiet hour changes nothing on disk. A bank that moves its rate
    (or the same page load parsed without a readable timestamp) gets a new key
    and a new row.
    """
    init()
    conn = _conn()
    fields = ("bank_code", "bank_name", "ccy", "channel", "buy", "sell",
              "flag", "bank_updated_at", "source_url")
    updates = ",".join(f"{f}=excluded.{f}" for f in fields[1:]) + ", synced_at=excluded.synced_at"
    fetched = _now()
    written = 0
    try:
        for row in rows or []:
            bank_code = str(row.get("bank_code") or "").strip()
            ccy = str(row.get("ccy") or "").strip().upper()
            channel = str(row.get("channel") or "").strip().upper()
            if not bank_code or not ccy or not channel:
                continue
            # The key must never be NULL — PostgreSQL rejects that in a
            # primary key — so an unparsed source timestamp falls back to our
            # own fetch time, which still keys a real, distinct poll.
            updated_at = str(row.get("bank_updated_at") or fetched)
            values = [bank_code, row.get("bank_name"), ccy, channel,
                     row.get("buy"), row.get("sell"), row.get("flag"),
                     updated_at, row.get("source_url"), fetched]
            conn.execute(
                f"INSERT INTO bank_fx_rates ({','.join(fields)}, synced_at) "
                f"VALUES ({','.join('?' * (len(fields) + 1))}) "
                f"ON CONFLICT(bank_code, ccy, channel, bank_updated_at) DO UPDATE SET {updates}",
                values)
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def bank_fx_rates_latest() -> list[dict[str, Any]]:
    """The newest row per (bank, currency, channel) — the board a reader sees."""
    init()
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            """
            SELECT bank_code, bank_name, ccy, channel, buy, sell, flag,
                   bank_updated_at, source_url, synced_at
            FROM bank_fx_rates b
            WHERE bank_updated_at = (
                SELECT MAX(bank_updated_at) FROM bank_fx_rates
                WHERE bank_code = b.bank_code AND ccy = b.ccy AND channel = b.channel
            )
            ORDER BY bank_name, ccy, channel
            """)]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bridging the existing catalog into the registry
# ---------------------------------------------------------------------------

_FORM_TITLES = {"NSBU": "НСБУ", "MSFO": "МСФО", "Audition": "Аудиторское заключение"}


def compose_title(report_form: str, period_type: str, year: Any,
                  quarter: Any = None) -> str:
    """A readable name for a report whose stored title is empty (ТЗ Б.1).

    Every title in the database is blank, so the interface assembles one on the
    client from the form and the period. Composing it once, here, means the
    catalog, the audit report and any export say the same thing — three places
    inventing the same string is three chances to disagree.
    """
    form = _FORM_TITLES.get(str(report_form), str(report_form or "Отчёт"))
    if quarter:
        return f"{form}, {year} Q{int(quarter)}"
    if str(period_type) == "annual":
        return f"{form}, годовой {year}"
    return f"{form}, {year}"


def sync_from_catalog() -> dict[str, int]:
    """Register what the catalog already knows as `discovered` reports.

    The project has been collecting `catalog_companies` and `catalog_reports` for
    a long time; what it never had was a state for each report or a link from a
    published figure back to one. So the registry is seeded from those tables
    rather than started empty — the provenance layer describes the filings we
    actually hold, from the first run.

    Idempotent: a report already registered keeps its state, so a nightly sync
    does not reset something that has been parsed.

    Reads first, then writes in batches. The row-at-a-time version issued a
    SELECT and a write per catalogued report, which is free against a local
    SQLite file and a network round trip each against PostgreSQL: measured over
    1 883 filings, /api/admin/catalog/register spent 7 670 statements and
    outlasted the collector's 120s read timeout, failing the daily run of
    2026-08-03. The same work is now 7.
    """
    init()
    conn = _conn()
    try:
        # ТЗ Б.6: the catalog is a list of ISSUERS. 73 ticker rows are 66
        # organisations; keying by ticker is why a bond series showed "0 отчётов"
        # while its issuer's filings sat under another ticker.
        issuer_rows = [(r["org_id"], r["name"], r["synced"]) for r in conn.execute(
            "SELECT org_id, MIN(company_name) AS name, MAX(last_synced_at) AS synced "
            "FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != '' "
            "GROUP BY org_id")]

        # What is already registered, in one read rather than one per report.
        existing = {
            _registry_key(r["org_id"], r["report_form"], r["period_type"],
                          r["period_year"], r["period_quarter"]): r["id"]
            for r in conn.execute(
                "SELECT id, org_id, report_form, period_type, period_year, "
                "       period_quarter FROM source_reports")}

        # Two tickers of one issuer file the SAME report (ALKB and ALKBP share
        # Aloqabank's filings), so the catalog holds several rows per registry
        # key. The old loop collapsed them by re-reading its own writes; a batch
        # has to collapse them here or the UNIQUE constraint rejects it — with
        # the same COALESCE precedence, a later non-null value winning.
        merged: dict[tuple, dict[str, Any]] = {}
        for row in conn.execute(
                "SELECT r.ticker, r.report_form, r.period_type, r.year, r.quarter, "
                "       r.title, r.pdf_url, r.excel_url, c.org_id "
                "FROM catalog_reports r LEFT JOIN catalog_companies c ON c.ticker = r.ticker "
                "WHERE r.year IS NOT NULL"):
            org_id = row["org_id"] or f"ticker:{row['ticker']}"
            quarter = row["quarter"] or None
            key = _registry_key(org_id, row["report_form"], row["period_type"],
                                row["year"], quarter)
            item = merged.get(key)
            if item is None:
                merged[key] = {
                    "org_id": org_id, "report_form": row["report_form"],
                    "period_type": row["period_type"], "year": row["year"],
                    "quarter": quarter, "pdf_url": row["pdf_url"],
                    "excel_url": row["excel_url"],
                    "title": row["title"] or compose_title(
                        row["report_form"], row["period_type"], row["year"], quarter),
                }
                continue
            for field in ("pdf_url", "excel_url", "title"):
                if row[field] is not None:
                    item[field] = row[field]

        updates, inserts = [], []
        now = _now()
        for key, item in merged.items():
            report_id = existing.get(key)
            if report_id is not None:
                updates.append((item["pdf_url"], item["excel_url"], item["title"], report_id))
            else:
                inserts.append((item["org_id"], item["report_form"], item["period_type"],
                                item["year"], item["quarter"], item["title"],
                                item["pdf_url"], item["excel_url"], now))

        if issuer_rows:
            conn.executemany(
                "INSERT INTO issuers (org_id, name, synced_at) VALUES (?,?,?) "
                "ON CONFLICT(org_id) DO UPDATE SET name=excluded.name, "
                "synced_at=COALESCE(excluded.synced_at, issuers.synced_at)",
                issuer_rows)
        if updates:
            conn.executemany(
                "UPDATE source_reports SET pdf_url=COALESCE(?, pdf_url), "
                "excel_url=COALESCE(?, excel_url), title=COALESCE(?, title) WHERE id=?",
                updates)
        if inserts:
            conn.executemany(
                "INSERT INTO source_reports (org_id, report_form, period_type, "
                "period_year, period_quarter, title, pdf_url, excel_url, state, "
                "discovered_at) VALUES (?,?,?,?,?,?,?,?, 'discovered', ?)",
                inserts)
        conn.commit()
    finally:
        conn.close()
    return {"issuers": len(issuer_rows), "reports_registered": len(inserts)}


def _registry_key(org_id: Any, report_form: Any, period_type: Any,
                  period_year: Any, period_quarter: Any) -> tuple:
    """The tuple `source_reports`' UNIQUE constraint is built on.

    `IFNULL(period_quarter,-1)` in SQL; an annual report has no quarter and two
    of them must still collide, so the sentinel travels into Python unchanged.
    """
    return (str(org_id), str(report_form), str(period_type), int(period_year),
            int(period_quarter) if period_quarter else -1)


def report_id_for(ticker: str, report_form: str, period_type: str, year: int,
                  quarter: int | None = None) -> int | None:
    """The registry id of a report, resolved the way the parser identifies it."""
    init()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT r.id FROM source_reports r "
            "LEFT JOIN catalog_companies c ON c.org_id = r.org_id "
            "WHERE (c.ticker = ? OR r.org_id = ?) AND r.report_form = ? "
            "AND r.period_type = ? AND r.period_year = ? "
            "AND IFNULL(r.period_quarter,-1) = IFNULL(?,-1) LIMIT 1",
            (ticker, f"ticker:{ticker}", report_form, period_type, year,
             quarter or None)).fetchone()
        return int(row["id"]) if row else None
    finally:
        conn.close()


def ticker_of(report_id: int) -> str | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COALESCE(c.ticker, REPLACE(r.org_id,'ticker:','')) AS ticker "
            "FROM source_reports r LEFT JOIN catalog_companies c ON c.org_id = r.org_id "
            "WHERE r.id = ? LIMIT 1", (report_id,)).fetchone()
        return row["ticker"] if row else None
    finally:
        conn.close()
